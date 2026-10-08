"""HTTP behavior of the /tasks endpoints, against the test database.

Detailed field rules are covered in tests/test_schemas.py. These tests check
routing, status codes, headers, response shapes and the request transaction.
Error *bodies* are not asserted yet: the single error structure is Step 7.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, delete

from app.api import get_services
from app.db import tasks
from app.main import app
from app.repository import TaskRepository
from app.service import TaskService

from .conftest import FakeClock

START_JSON = "2026-01-01T09:00:00Z"


class RolledBackServices:
    """Test stand-in for TaskServices: uses the test connection and fake clock.

    It never commits; the `connection` fixture rolls everything back.
    """

    def __init__(self, connection: Connection, clock: FakeClock) -> None:
        self._connection = connection
        self._clock = clock

    @contextmanager
    def begin(self) -> Iterator[TaskService]:
        yield TaskService(TaskRepository(self._connection), clock=self._clock)


@pytest.fixture
def client(connection: Connection, clock: FakeClock) -> Iterator[TestClient]:
    """Client whose requests use the test connection (rolled back after the test)."""
    services = RolledBackServices(connection, clock)
    app.dependency_overrides[get_services] = lambda: services
    yield TestClient(app)
    app.dependency_overrides.clear()


def create(client: TestClient, **body: object) -> dict[str, object]:
    response = client.post("/tasks", json={"title": "Fix printer", **body})
    assert response.status_code == 201, response.text
    return response.json()


# --- POST /tasks ----------------------------------------------------------------


def test_create_returns_201_with_the_task(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "  Fix printer  "})

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": body["id"],
        "title": "Fix printer",
        "description": None,
        "status": "todo",
        "priority": "medium",
        "created_at": START_JSON,
        "updated_at": START_JSON,
    }
    assert isinstance(body["id"], int)


def test_create_sets_location_header_to_the_new_task(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "Fix printer"})

    location = response.headers["location"]
    assert location == f"/tasks/{response.json()['id']}"
    assert client.get(location).json() == response.json()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": "   "},
        {"title": None},
        {"title": "t" * 256},
        {"title": "t", "description": "d" * 5001},
        {"title": "t", "status": "urgent"},
        {"title": "t", "priority": 3},
        {"title": "t", "unknown": 1},
    ],
)
def test_create_rejects_invalid_body(client: TestClient, body: dict[str, object]) -> None:
    assert client.post("/tasks", json=body).status_code == 422


def test_create_rejects_malformed_json_with_400(client: TestClient) -> None:
    response = client.post(
        "/tasks", content="{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 400


# --- GET /tasks/{id} ------------------------------------------------------------


def test_get_returns_the_task(client: TestClient) -> None:
    created = create(client, description="Floor 2")

    response = client.get(f"/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.parametrize("task_id", ["999999", "2147483647"])
def test_get_unknown_id_returns_404(client: TestClient, task_id: str) -> None:
    assert client.get(f"/tasks/{task_id}").status_code == 404


def test_unknown_id_returns_problem_details(client: TestClient) -> None:
    response = client.get("/tasks/999999")

    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Task 999999 not found.",
        "errors": [],
    }


@pytest.mark.parametrize(
    "task_id",
    ["abc", "1.5", "1e3", "0", "-1", "2147483648", "99999999999999999999"],
)
@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_malformed_or_out_of_range_id_is_rejected(
    client: TestClient, method: str, task_id: str
) -> None:
    # Ids are integers in 1..2147483647; anything else is invalid input.
    response = client.request(method, f"/tasks/{task_id}", json={})

    assert response.status_code == 422


# --- GET /tasks -----------------------------------------------------------------


def test_list_without_tasks_returns_empty_page(client: TestClient) -> None:
    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_list_returns_newest_first_with_pagination(
    client: TestClient, clock: FakeClock
) -> None:
    ids = []
    for i in range(3):
        ids.append(create(client, title=f"task {i}")["id"])
        clock.advance()

    body = client.get("/tasks", params={"limit": 2, "offset": 1}).json()

    assert [item["id"] for item in body["items"]] == [ids[1], ids[0]]
    assert (body["total"], body["limit"], body["offset"]) == (3, 2, 1)


def test_list_combines_filters(client: TestClient) -> None:
    match = create(client, status="done", priority="high")
    create(client, status="done", priority="low")
    create(client, status="todo", priority="high")

    body = client.get("/tasks", params={"status": "done", "priority": "high"}).json()

    assert body["items"] == [match]
    assert body["total"] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "101"},
        {"limit": "500"},
        {"offset": "-1"},
        {"limit": "abc"},
        {"status": "urgent"},
        {"priority": "HIGH"},
    ],
)
def test_list_rejects_invalid_query(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/tasks", params=params).status_code == 422


@pytest.mark.parametrize(
    ("query", "expected_limit"),
    [
        ("limit=1&limit=2", 2),
        ("limit=2&limit=1", 1),
        # Earlier values are ignored and not validated, even if invalid.
        ("limit=abc&limit=2", 2),
        ("limit=500&limit=2", 2),
    ],
)
def test_repeated_scalar_query_parameter_uses_the_last_value(
    client: TestClient, query: str, expected_limit: int
) -> None:
    # Documented contract (FastAPI's behavior, pinned here so an upgrade that
    # changes it is noticed): the last value of a repeated parameter wins.
    for i in range(3):
        create(client, title=f"task {i}")

    response = client.get(f"/tasks?{query}")

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == expected_limit
    assert len(body["items"]) == expected_limit


def test_repeated_parameter_is_still_validated_on_its_last_value(
    client: TestClient,
) -> None:
    response = client.get("/tasks?limit=2&limit=500")

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "limit"


def test_repeated_filter_uses_the_last_value(client: TestClient) -> None:
    create(client, status="todo")
    done = create(client, status="done")

    body = client.get("/tasks?status=todo&status=done").json()

    assert body["items"] == [done]


# --- PATCH /tasks/{id} ----------------------------------------------------------


def test_patch_updates_fields_and_bumps_updated_at(
    client: TestClient, clock: FakeClock
) -> None:
    created = create(client)
    clock.advance()

    response = client.patch(f"/tasks/{created['id']}", json={"status": "done"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["created_at"] == START_JSON
    assert body["updated_at"] == "2026-01-01T10:00:00Z"
    assert client.get(f"/tasks/{created['id']}").json() == body


@pytest.mark.parametrize(
    "body",
    [{}, {"title": "  Fix printer  ", "status": "todo"}],
    ids=["empty", "same-values"],
)
def test_patch_without_effective_change_keeps_updated_at(
    client: TestClient, clock: FakeClock, body: dict[str, object]
) -> None:
    created = create(client)
    clock.advance()

    response = client.patch(f"/tasks/{created['id']}", json=body)

    assert response.status_code == 200
    assert response.json() == created


def test_patch_description_null_clears_and_omitted_keeps(client: TestClient) -> None:
    created = create(client, description="Floor 2")

    kept = client.patch(f"/tasks/{created['id']}", json={"priority": "high"}).json()
    cleared = client.patch(f"/tasks/{created['id']}", json={"description": None}).json()

    assert kept["description"] == "Floor 2"
    assert cleared["description"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"title": None},
        {"status": None},
        {"priority": None},
        {"title": ""},
        {"status": "urgent"},
        {"unknown": 1},
    ],
)
def test_patch_rejects_invalid_body(client: TestClient, body: dict[str, object]) -> None:
    created = create(client)

    assert client.patch(f"/tasks/{created['id']}", json=body).status_code == 422


@pytest.mark.parametrize("body", [{"status": "done"}, {}])
def test_patch_unknown_id_returns_404(client: TestClient, body: dict[str, object]) -> None:
    assert client.patch("/tasks/999999", json=body).status_code == 404


# --- DELETE /tasks/{id} ---------------------------------------------------------


def test_delete_returns_204_without_body(client: TestClient) -> None:
    created = create(client)

    response = client.delete(f"/tasks/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/tasks/{created['id']}").status_code == 404


def test_delete_unknown_id_returns_404(client: TestClient) -> None:
    assert client.delete("/tasks/999999").status_code == 404


# --- Request transaction --------------------------------------------------------


def test_successful_request_commits(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "engine", engine, raising=False)
    client = TestClient(app)

    task_id = client.post("/tasks", json={"title": "Committed"}).json()["id"]
    try:
        # A brand-new connection only sees committed data.
        with engine.connect() as other:
            assert TaskRepository(other).get(task_id) is not None
    finally:
        with engine.begin() as cleanup:
            cleanup.execute(delete(tasks).where(tasks.c.id == task_id))


def test_failed_commit_is_reported_as_an_error(
    connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CommitFailsEngine:
        @contextmanager
        def begin(self) -> Iterator[Connection]:
            yield connection
            raise RuntimeError("commit failed")

    monkeypatch.setattr(app.state, "engine", CommitFailsEngine(), raising=False)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/tasks", json={"title": "Never committed"})

    # The transaction ends inside the route, before the response is sent, so
    # the client sees the failure instead of a 201 for data never saved.
    assert response.status_code == 500
