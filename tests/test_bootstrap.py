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
