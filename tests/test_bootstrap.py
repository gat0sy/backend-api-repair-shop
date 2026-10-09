import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_openapi_schema_is_served() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Repair Shop Task API"


def test_swagger_ui_is_served() -> None:
    response = client.get("/docs")

    assert response.status_code == 200


def test_api_version_matches_pyproject() -> None:
    # The version lives in two places (pyproject.toml and the OpenAPI info in
    # app/main.py); this keeps them from drifting apart.
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    version = tomllib.loads(pyproject.read_text())["project"]["version"]

    assert app.version == version
    assert client.get("/openapi.json").json()["info"]["version"] == version
