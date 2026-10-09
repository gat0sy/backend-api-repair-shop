"""CORS for browser frontends (no database needed).

None of these requests reach the database: preflights are answered by the
CORS layer, and the other requests fail validation first.
"""

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import ValidationError

from app.config import CorsSettings
from app.main import create_app

ALLOWED = "http://localhost:3000"
OTHER = "http://evil.example"
PROBLEM_KEYS = {"type", "title", "status", "detail", "errors"}


def cors_client(origins: list[str]) -> TestClient:
    app = create_app(cors_origins=origins)
    # The lifespan (which creates the engine) doesn't run here, and no request
    # in this file reaches a route body, so a placeholder engine is enough.
    app.state.engine = None
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return cors_client([ALLOWED])


def preflight(
    client: TestClient,
    origin: str,
    method: str = "PATCH",
    headers: str = "content-type",
) -> Response:
    return client.options(
        "/tasks/1",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


# --- Configuration ----------------------------------------------------------------


def settings_from(value: str, monkeypatch: pytest.MonkeyPatch) -> CorsSettings:
    monkeypatch.setenv("CORS_ORIGINS", value)
    return CorsSettings(_env_file=None)


def test_no_origins_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert CorsSettings(_env_file=None).cors_origins == []


def test_origins_are_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_from(
        " http://localhost:3000 , https://app.example.com,", monkeypatch
    )

    assert settings.cors_origins == ["http://localhost:3000", "https://app.example.com"]


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "http://localhost:3000,*",
        "http://localhost:3000/",
        "https://app.example.com/path",
        "localhost:3000",
        "ftp://files.example.com",
    ],
)
def test_wildcard_and_non_origins_are_rejected(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValidationError):
        settings_from(value, monkeypatch)


# --- Preflight (OPTIONS) ----------------------------------------------------------


def test_allowed_preflight(client: TestClient) -> None:
    response = preflight(client, ALLOWED)

    assert response.status_code == 200
    headers = response.headers
    assert headers["access-control-allow-origin"] == ALLOWED
    assert "PATCH" in headers["access-control-allow-methods"]
    assert "content-type" in headers["access-control-allow-headers"].lower()


@pytest.mark.parametrize(
    ("origin", "method", "headers", "failed"),
    [
        (OTHER, "PATCH", "content-type", "origin"),
        (ALLOWED, "PUT", "content-type", "method"),
        (ALLOWED, "PATCH", "x-custom", "headers"),
    ],
    ids=["disallowed-origin", "disallowed-method", "disallowed-header"],
)
def test_rejected_preflight_is_problem_details(
    client: TestClient, origin: str, method: str, headers: str, failed: str
) -> None:
    response = preflight(client, origin, method, headers)

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert set(body) == PROBLEM_KEYS
    assert body["detail"] == f"CORS preflight rejected: {failed} not allowed."
    if failed == "origin":
        # An allowed origin still gets Access-Control-Allow-Origin (Starlette's
        # behavior); the browser then blocks on the method or header instead.
        assert "access-control-allow-origin" not in response.headers


# --- Actual requests --------------------------------------------------------------


def test_allowed_origin_can_read_responses(client: TestClient) -> None:
    response = client.get("/tasks/abc", headers={"Origin": ALLOWED})

    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "location" in response.headers["access-control-expose-headers"].lower()


def test_disallowed_origin_gets_no_cors_headers(client: TestClient) -> None:
    response = client.get("/tasks/abc", headers={"Origin": OTHER})

    assert response.status_code == 422
    assert "access-control-allow-origin" not in response.headers


def test_without_configured_origins_cors_is_off() -> None:
    client = cors_client([])

    response = preflight(client, ALLOWED)

    # No CORS layer: OPTIONS is just an unsupported method.
    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers
