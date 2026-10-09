"""Invalid requests are rejected at the API boundary (no database needed).

The real dependency and routes run, with a stand-in engine that records every
attempt to open a transaction. An invalid request must be rejected with 422
before any transaction is opened, so it never reaches the service, the
repository or SQL.
"""

from typing import NoReturn

import pytest
from fastapi.testclient import TestClient

from app.api import MAX_TASK_ID
from app.main import app


class RecordingEngine:
    """Records `begin()` calls, then fails: no request may get further."""

    def __init__(self) -> None:
        self.begin_calls = 0

    def begin(self) -> NoReturn:
        self.begin_calls += 1
        raise RuntimeError("database reached")


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> RecordingEngine:
    engine = RecordingEngine()
    monkeypatch.setattr(app.state, "engine", engine, raising=False)
    return engine


@pytest.fixture
def client(engine: RecordingEngine) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


BAD_IDS = ["0", "-1", str(MAX_TASK_ID + 1), "99999999999999999999", "abc", "1.5"]


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
@pytest.mark.parametrize("task_id", BAD_IDS)
def test_invalid_id_never_opens_a_transaction(
    client: TestClient, engine: RecordingEngine, method: str, task_id: str
) -> None:
    response = client.request(method, f"/tasks/{task_id}", json={})

    assert response.status_code == 422
    assert engine.begin_calls == 0


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/tasks", {}),
        ("POST", "/tasks", {"title": "   "}),
        ("POST", "/tasks", {"title": "t", "status": "urgent"}),
        ("POST", "/tasks", {"title": "t", "unknown": 1}),
        ("PATCH", "/tasks/1", {"status": None}),
        ("PATCH", "/tasks/1", {"title": "t" * 256}),
    ],
)
def test_invalid_body_never_opens_a_transaction(
    client: TestClient, engine: RecordingEngine, method: str, path: str, body: object
) -> None:
    response = client.request(method, path, json=body)

    assert response.status_code == 422
    assert engine.begin_calls == 0


@pytest.mark.parametrize(
    ("method", "path", "params"),
    [
        ("GET", "/tasks", {"limit": "0"}),
        ("GET", "/tasks", {"limit": "101"}),
        ("GET", "/tasks", {"offset": "-1"}),
        ("GET", "/tasks", {"status": "x"}),
        ("GET", "/tasks", {"foo": "1"}),
        ("GET", "/tasks/1", {"foo": "1"}),
        ("POST", "/tasks", {"foo": "1"}),
        ("PATCH", "/tasks/1", {"foo": "1"}),
        ("DELETE", "/tasks/1", {"foo": "1"}),
    ],
)
def test_invalid_query_never_opens_a_transaction(
    client: TestClient,
    engine: RecordingEngine,
    method: str,
    path: str,
    params: dict[str, str],
) -> None:
    response = client.request(method, path, params=params, json={"title": "t"})

    assert response.status_code == 422
    assert engine.begin_calls == 0


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/tasks", {"title": "t"}),
        ("GET", "/tasks", None),
        ("GET", "/tasks/1", None),
        ("PATCH", f"/tasks/{MAX_TASK_ID}", {}),
        ("DELETE", "/tasks/1", None),
    ],
)
def test_valid_request_opens_exactly_one_transaction(
    client: TestClient, engine: RecordingEngine, method: str, path: str, body: object
) -> None:
    # Positive control: proves the stand-in engine really sees requests that
    # pass validation (it then fails them on purpose, hence the 500).
    response = client.request(method, path, json=body)

    assert response.status_code == 500
    assert engine.begin_calls == 1


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_id_range_is_part_of_the_openapi_contract(method: str) -> None:
    operation = app.openapi()["paths"]["/tasks/{task_id}"][method]
    (task_id,) = [p for p in operation["parameters"] if p["name"] == "task_id"]

    assert task_id["schema"]["type"] == "integer"
    assert task_id["schema"]["minimum"] == 1
    assert task_id["schema"]["maximum"] == MAX_TASK_ID


@pytest.mark.parametrize(
    ("method", "path"), [("POST", "/tasks"), ("PATCH", "/tasks/1")]
)
def test_non_json_body_never_opens_a_transaction(
    client: TestClient, engine: RecordingEngine, method: str, path: str
) -> None:
    response = client.request(
        method, path, content=b"title=t", headers={"content-type": "text/plain"}
    )

    assert response.status_code == 415
    assert engine.begin_calls == 0
