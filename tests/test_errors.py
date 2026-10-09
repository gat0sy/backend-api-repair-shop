"""The single error structure (RFC 9457 Problem Details), no database needed.

Every error response must have Content-Type application/problem+json and
exactly the keys type, title, status, detail and errors.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from app.api import get_services
from app.main import app
from app.service import TaskNotFoundError

PROBLEM_KEYS = {"type", "title", "status", "detail", "errors"}


class FailingService:
    """Every service call raises the configured exception."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def __getattr__(self, name: str) -> object:
        def fail(*args: object, **kwargs: object) -> None:
            raise self._error

        return fail


class StubServices:
    def __init__(self) -> None:
        self.error: Exception = TaskNotFoundError(42)

    @contextmanager
    def begin(self) -> Iterator[FailingService]:
        yield FailingService(self.error)


@pytest.fixture
def services() -> Iterator[StubServices]:
    services = StubServices()
    app.dependency_overrides[get_services] = lambda: services
    yield services
    app.dependency_overrides.clear()


@pytest.fixture
def client(services: StubServices) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def assert_problem(response: Response, status: int, title: str) -> dict[str, object]:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, object] = response.json()
    assert set(body) == PROBLEM_KEYS
    assert body["type"] == "about:blank"
    assert body["title"] == title
    assert body["status"] == status
    assert isinstance(body["detail"], str) and body["detail"]
    assert isinstance(body["errors"], list)
    return body


# --- One structure for every kind of error --------------------------------------


@pytest.mark.parametrize(
    ("method", "url", "kwargs", "status", "title"),
    [
        (
            "POST",
            "/tasks",
            {"content": "{bad", "headers": {"content-type": "application/json"}},
            400,
            "Bad Request",
        ),
        ("GET", "/tasks/42", {}, 404, "Not Found"),
        ("GET", "/nope", {}, 404, "Not Found"),
        ("GET", "/tasks/", {}, 404, "Not Found"),
        ("PUT", "/tasks/1", {"json": {}}, 405, "Method Not Allowed"),
        ("POST", "/tasks", {"json": {}}, 422, "Unprocessable Content"),
        ("GET", "/tasks", {"params": {"limit": "0"}}, 422, "Unprocessable Content"),
        ("GET", "/tasks/abc", {}, 422, "Unprocessable Content"),
    ],
    ids=[
        "malformed-json",
        "task-not-found",
        "unknown-url",
        "trailing-slash",
        "wrong-method",
        "invalid-body",
        "invalid-query",
        "invalid-path",
    ],
)
def test_every_error_uses_the_problem_structure(
    client: TestClient,
    method: str,
    url: str,
    kwargs: dict[str, object],
    status: int,
    title: str,
) -> None:
    assert_problem(client.request(method, url, **kwargs), status, title)  # type: ignore[arg-type]


def test_unexpected_error_is_500_without_internal_details(
    client: TestClient, services: StubServices
) -> None:
    services.error = RuntimeError("secret connection string")

    response = client.get("/tasks/1")

    body = assert_problem(response, 500, "Internal Server Error")
    assert body["detail"] == "An unexpected error occurred."
    assert body["errors"] == []
    assert "secret" not in response.text


# --- 400 / 404 / 405 ------------------------------------------------------------


def test_malformed_json_is_400_without_field_errors(client: TestClient) -> None:
    response = client.post(
        "/tasks", content='{"title": "x",', headers={"content-type": "application/json"}
    )

    body = assert_problem(response, 400, "Bad Request")
    assert body["detail"] == "The request body is not valid JSON."
    assert body["errors"] == []


def test_task_not_found_names_the_id(client: TestClient) -> None:
    body = assert_problem(client.get("/tasks/42"), 404, "Not Found")

    assert body["detail"] == "Task 42 not found."
    assert body["errors"] == []


def test_trailing_slash_is_not_redirected(client: TestClient) -> None:
    response = client.get("/tasks/", follow_redirects=False)

    assert_problem(response, 404, "Not Found")


@pytest.mark.parametrize(
    ("url", "expected"),
    [("/tasks/1", {"GET", "PATCH", "DELETE"}), ("/tasks", {"GET", "POST"})],
)
def test_wrong_method_lists_every_allowed_method(
    client: TestClient, url: str, expected: set[str]
) -> None:
    response = client.put(url, json={})

    assert_problem(response, 405, "Method Not Allowed")
    allowed = {m.strip() for m in response.headers["allow"].split(",")}
    assert allowed == expected


# --- 422: field-level errors ----------------------------------------------------


def errors_of(response: Response) -> list[dict[str, object]]:
    body = assert_problem(response, 422, "Unprocessable Content")
    assert body["detail"] == "The request contains invalid data."
    return body["errors"]  # type: ignore[return-value]


def test_body_error_names_location_field_and_message(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "t" * 256})

    assert errors_of(response) == [
        {
            "location": "body",
            "field": "title",
            "message": "title must be at most 255 characters",
        }
    ]


def test_domain_value_error_message_has_no_framework_prefix(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "   "})

    assert errors_of(response) == [
        {
            "location": "body",
            "field": "title",
            "message": "title must not be empty or whitespace-only",
        }
    ]


def test_all_problems_are_reported_at_once(client: TestClient) -> None:
    response = client.post(
        "/tasks", json={"description": "d" * 5001, "status": "urgent", "owner": "me"}
    )

    fields = {(e["location"], e["field"]) for e in errors_of(response)}
    assert fields == {
        ("body", "title"),
        ("body", "description"),
        ("body", "status"),
        ("body", "owner"),
    }


def test_unknown_body_field_message(client: TestClient) -> None:
    response = client.patch("/tasks/1", json={"owner": "me"})

    assert errors_of(response) == [
        {"location": "body", "field": "owner", "message": "Unknown field."}
    ]


def test_missing_body_has_no_field(client: TestClient) -> None:
    (error,) = errors_of(client.post("/tasks"))

    assert error["location"] == "body"
    assert error["field"] is None


def test_query_error_location(client: TestClient) -> None:
    (error,) = errors_of(client.get("/tasks", params={"limit": "500"}))

    assert (error["location"], error["field"]) == ("query", "limit")


def test_path_error_location(client: TestClient) -> None:
    (error,) = errors_of(client.get("/tasks/0"))

    assert (error["location"], error["field"]) == ("path", "task_id")


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/tasks?foo=1"),
        ("GET", "/tasks/1?foo=1"),
        ("POST", "/tasks?foo=1"),
        ("PATCH", "/tasks/1?foo=1"),
        ("DELETE", "/tasks/1?foo=1"),
    ],
)
def test_unknown_query_parameter_is_rejected_everywhere(
    client: TestClient, method: str, url: str
) -> None:
    response = client.request(method, url, json={"title": "t"})

    assert errors_of(response) == [
        {"location": "query", "field": "foo", "message": "Unknown query parameter."}
    ]


def test_client_input_is_not_echoed(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "t", "status": "secret-value-123"})

    errors_of(response)
    assert "secret-value-123" not in response.text


# --- 415: request body media type -----------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "text/plain"},
        {"content-type": "application/x-www-form-urlencoded"},
        {"content-type": "application/merge-patch+json"},
        {},
    ],
    ids=["text-plain", "form", "merge-patch", "missing"],
)
def test_non_json_body_is_415(
    client: TestClient, method: str, headers: dict[str, str]
) -> None:
    url = "/tasks" if method == "POST" else "/tasks/1"

    response = client.request(method, url, content=b'{"title": "t"}', headers=headers)

    body = assert_problem(response, 415, "Unsupported Media Type")
    assert body["errors"] == []


@pytest.mark.parametrize(
    "content_type", ["application/json; charset=utf-8", "Application/JSON"]
)
def test_json_media_type_parameters_and_case_are_accepted(
    client: TestClient, content_type: str
) -> None:
    # Reaches the service (stubbed to report not-found), so the media type passed.
    response = client.patch(
        "/tasks/1",
        content=b'{"status": "done"}',
        headers={"content-type": content_type},
    )

    assert response.status_code == 404


def test_missing_body_without_content_type_is_still_422(client: TestClient) -> None:
    (error,) = errors_of(client.post("/tasks"))

    assert (error["location"], error["field"], error["message"]) == (
        "body",
        None,
        "Field required",
    )
