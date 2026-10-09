"""Full-stack integration tests: the app exactly as it runs in production.

No dependency overrides. The real lifespan creates the engine from
DATABASE_URL (pointed at the test database), requests go through
TaskServices.begin(), and data is really committed. The table is emptied
before and after each test, since nothing is rolled back automatically.
"""

import threading
from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.domain import TaskStatus, TaskUpdate
from app.main import app
from app.repository import TaskRepository
from app.service import TaskService


def empty_tasks_table(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tasks RESTART IDENTITY"))


@pytest.fixture
def live_client(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    empty_tasks_table(engine)
    with TestClient(app) as client:  # `with` runs the lifespan (startup/shutdown)
        yield client
    empty_tasks_table(engine)


def committed_task_count(engine: Engine) -> int:
    # A separate connection only sees committed data.
    with engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM tasks")).scalar_one()


# --- Wiring -----------------------------------------------------------------------


def test_lifespan_connects_to_the_configured_database(
    live_client: TestClient, engine: Engine
) -> None:
    assert app.state.engine.url.database == engine.url.database


# --- A realistic client session ---------------------------------------------------


def test_task_lifecycle_end_to_end(live_client: TestClient, engine: Engine) -> None:
    # Create two tasks; the Location header points at each one.
    first = live_client.post("/tasks", json={"title": "Replace toner"})
    second = live_client.post(
        "/tasks", json={"title": "Fix printer", "priority": "high"}
    )
    assert (first.status_code, second.status_code) == (201, 201)
    first_task, second_task = first.json(), second.json()
    assert live_client.get(first.headers["location"]).json() == first_task
    assert committed_task_count(engine) == 2

    # Real clock: timezone-aware UTC, serialized with "Z".
    assert first_task["created_at"].endswith("Z")
    assert first_task["created_at"] == first_task["updated_at"]

    # List: newest first, with total.
    listing = live_client.get("/tasks").json()
    assert [t["id"] for t in listing["items"]] == [second_task["id"], first_task["id"]]
    assert (listing["total"], listing["limit"], listing["offset"]) == (2, 20, 0)

    # A real change bumps updated_at; created_at stays.
    changed = live_client.patch(
        f"/tasks/{first_task['id']}", json={"status": "in_progress"}
    ).json()
    assert changed["status"] == "in_progress"
    assert changed["created_at"] == first_task["created_at"]
    assert datetime.fromisoformat(changed["updated_at"]) > datetime.fromisoformat(
        first_task["updated_at"]
    )

    # A no-op PATCH changes nothing, including updated_at.
    unchanged = live_client.patch(
        f"/tasks/{first_task['id']}", json={"status": "in_progress"}
    ).json()
    assert unchanged == changed

    # Filtered list reflects the committed change.
    in_progress = live_client.get("/tasks", params={"status": "in_progress"}).json()
    assert [t["id"] for t in in_progress["items"]] == [first_task["id"]]

    # Delete, then it's gone everywhere.
    assert live_client.delete(f"/tasks/{first_task['id']}").status_code == 204
    assert live_client.get(f"/tasks/{first_task['id']}").status_code == 404
    assert live_client.get("/tasks").json()["total"] == 1
    assert committed_task_count(engine) == 1


@pytest.mark.parametrize("description", ["", "   ", "  keep  surrounding  ", "é🔧"])
def test_description_round_trips_exactly(
    live_client: TestClient, description: str
) -> None:
    created = live_client.post(
        "/tasks", json={"title": "t", "description": description}
    ).json()

    stored = live_client.get(f"/tasks/{created['id']}").json()

    assert stored["description"] == description


# --- Transactions -----------------------------------------------------------------


def test_error_after_a_write_rolls_the_request_back(
    live_client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_create = TaskService.create_task

    def create_then_fail(self: TaskService, *args: object, **kwargs: object) -> None:
        original_create(self, *args, **kwargs)  # the INSERT happens...
        raise RuntimeError("failure after the write")  # ...then the request fails

    monkeypatch.setattr(TaskService, "create_task", create_then_fail)
    failing_client = TestClient(app, raise_server_exceptions=False)

    response = failing_client.post("/tasks", json={"title": "Half done"})

    assert response.status_code == 500
    assert committed_task_count(engine) == 0


def test_concurrent_patches_do_not_lose_updates(
    live_client: TestClient, engine: Engine
) -> None:
    task_id = live_client.post("/tasks", json={"title": "Fix printer"}).json()["id"]
    results: dict[str, int] = {}

    def patch_priority() -> None:
        response = live_client.patch(f"/tasks/{task_id}", json={"priority": "high"})
        results["status_code"] = response.status_code

    # Transaction A changes the status and keeps its transaction open.
    with engine.begin() as connection:
        TaskService(TaskRepository(connection)).update_task(
            task_id, TaskUpdate(status=TaskStatus.DONE)
        )

        # Meanwhile, request B changes the priority of the same task.
        request_b = threading.Thread(target=patch_priority)
        request_b.start()
        request_b.join(timeout=0.5)
        # B waits while A's transaction holds the row. (It would wait even
        # without SELECT ... FOR UPDATE, at its own UPDATE; the lock's job is to
        # make B wait *before reading*, so it doesn't write back a stale status.
        # The final assertion below is what proves that.)
        assert request_b.is_alive()
    # A commits here; B can now continue.

    request_b.join(timeout=5)
    assert not request_b.is_alive()
    assert results["status_code"] == 200

    # Both changes survive: neither request overwrote the other.
    final = live_client.get(f"/tasks/{task_id}").json()
    assert (final["status"], final["priority"]) == ("done", "high")
