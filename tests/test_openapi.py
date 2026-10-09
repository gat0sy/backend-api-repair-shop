"""The OpenAPI document matches the API's actual contract (no database needed)."""

import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.errors import Problem
from app.main import app

PROBLEM_REF = {"$ref": "#/components/schemas/Problem"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return app.openapi()


def operation(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    found: dict[str, Any] = spec["paths"][path][method]
    return found


EXPECTED_ERRORS = {
    ("post", "/tasks"): {"400", "415", "422", "500"},
    ("get", "/tasks"): {"422", "500"},
    ("get", "/tasks/{task_id}"): {"404", "422", "500"},
    ("patch", "/tasks/{task_id}"): {"400", "404", "415", "422", "500"},
    ("delete", "/tasks/{task_id}"): {"404", "422", "500"},
}


# --- Error responses ------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), list(EXPECTED_ERRORS))
def test_operation_documents_its_error_responses(
    spec: dict[str, Any], method: str, path: str
) -> None:
    responses = operation(spec, method, path)["responses"]
    errors = {code for code in responses if code.startswith(("4", "5"))}

    assert errors == EXPECTED_ERRORS[(method, path)]


@pytest.mark.parametrize(("method", "path"), list(EXPECTED_ERRORS))
def test_error_responses_are_problem_json_with_valid_examples(
    spec: dict[str, Any], method: str, path: str
) -> None:
    for code in EXPECTED_ERRORS[(method, path)]:
        content = operation(spec, method, path)["responses"][code]["content"]

        assert list(content) == ["application/problem+json"]
        assert content["application/problem+json"]["schema"] == PROBLEM_REF
        example = Problem.model_validate(content["application/problem+json"]["example"])
        assert example.status == int(code)


def test_framework_default_validation_schema_is_gone(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]

    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_every_schema_reference_resolves(spec: dict[str, Any]) -> None:
    referenced = set(re.findall(r"#/components/schemas/(\w+)", json.dumps(spec)))

    assert referenced <= set(spec["components"]["schemas"])


def test_problem_schema_requires_every_key(spec: dict[str, Any]) -> None:
    problem = spec["components"]["schemas"]["Problem"]

    assert set(problem["required"]) == {"type", "title", "status", "detail", "errors"}


def test_problem_schema_matches_real_error_responses() -> None:
    response = TestClient(app).get("/no-such-url")

    assert set(response.json()) == set(Problem.model_fields)


# --- Success responses ----------------------------------------------------------


def test_create_documents_location_header(spec: dict[str, Any]) -> None:
    created = operation(spec, "post", "/tasks")["responses"]["201"]

    assert "Location" in created["headers"]


def test_delete_documents_empty_204(spec: dict[str, Any]) -> None:
    deleted = operation(spec, "delete", "/tasks/{task_id}")["responses"]["204"]

    assert "content" not in deleted


# --- Parameters -----------------------------------------------------------------


def query_params(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    params = operation(spec, "get", "/tasks")["parameters"]
    return {p["name"]: p for p in params}


def test_list_parameters_are_exactly_the_contract(spec: dict[str, Any]) -> None:
    assert set(query_params(spec)) == {"status", "priority", "limit", "offset"}


@pytest.mark.parametrize(
    ("name", "enum"), [("status", "TaskStatus"), ("priority", "TaskPriority")]
)
def test_filters_are_optional_and_not_nullable(
    spec: dict[str, Any], name: str, enum: str
) -> None:
    param = query_params(spec)[name]

    assert param["required"] is False
    assert param["schema"]["$ref"] == f"#/components/schemas/{enum}"
    assert "anyOf" not in param["schema"]


def test_pagination_bounds_and_defaults(spec: dict[str, Any]) -> None:
    params = query_params(spec)
    limit, offset = params["limit"]["schema"], params["offset"]["schema"]

    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 100, 20)
    assert (offset["minimum"], offset["maximum"], offset["default"]) == (
        0,
        2**63 - 1,
        0,
    )


def test_enum_values_are_documented(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]

    assert schemas["TaskStatus"]["enum"] == ["todo", "in_progress", "done"]
    assert schemas["TaskPriority"]["enum"] == ["low", "medium", "high"]


# --- Request bodies -------------------------------------------------------------


def test_create_body_requires_only_title_and_forbids_extras(
    spec: dict[str, Any],
) -> None:
    create = spec["components"]["schemas"]["TaskCreate"]

    assert create["required"] == ["title"]
    assert create["additionalProperties"] is False
    assert (
        create["properties"]["title"]["minLength"],
        create["properties"]["title"]["maxLength"],
    ) == (1, 255)


def test_patch_body_has_no_required_fields_and_forbids_extras(
    spec: dict[str, Any],
) -> None:
    patch = spec["components"]["schemas"]["TaskPatch"]

    assert "required" not in patch
    assert patch["additionalProperties"] is False


@pytest.mark.parametrize("field", ["title", "status", "priority"])
def test_patch_fields_that_reject_null_are_not_nullable(
    spec: dict[str, Any], field: str
) -> None:
    schema = spec["components"]["schemas"]["TaskPatch"]["properties"][field]

    assert "anyOf" not in schema


def test_patch_description_is_nullable(spec: dict[str, Any]) -> None:
    schema = spec["components"]["schemas"]["TaskPatch"]["properties"]["description"]

    assert {"type": "null"} in schema["anyOf"]


def test_response_always_includes_description(spec: dict[str, Any]) -> None:
    task = spec["components"]["schemas"]["TaskResponse"]

    assert "description" in task["required"]
