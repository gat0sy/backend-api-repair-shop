"""Field-level rules of the request and response schemas (no database needed).

Request payloads are parsed from JSON text, exactly as the API receives them.
"""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ValidationError

from app.domain import UNSET, Task, TaskPriority, TaskStatus
from app.schemas import TaskCreate, TaskListQuery, TaskPatch, TaskResponse


def parse[M: BaseModel](model: type[M], data: object) -> M:
    return model.model_validate_json(json.dumps(data))


def assert_invalid(model: type[BaseModel], data: object) -> None:
    with pytest.raises(ValidationError):
        parse(model, data)


# --- TaskCreate -----------------------------------------------------------------


def test_create_minimal_body_gets_defaults() -> None:
    new = parse(TaskCreate, {"title": "Fix printer"}).to_domain()

    assert new.title == "Fix printer"
    assert new.description is None
    assert new.status is TaskStatus.TODO
    assert new.priority is TaskPriority.MEDIUM


def test_create_accepts_all_fields() -> None:
    body = {"title": "t", "description": "d", "status": "in_progress", "priority": "high"}

    new = parse(TaskCreate, body).to_domain()

    assert new.description == "d"
    assert new.status is TaskStatus.IN_PROGRESS
    assert new.priority is TaskPriority.HIGH


def test_create_strips_title() -> None:
    assert parse(TaskCreate, {"title": "  Fix printer  "}).title == "Fix printer"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": None},
        {"title": ""},
        {"title": "   "},
        {"title": "\t\n"},
        {"title": 123},
    ],
    ids=["missing", "null", "empty", "spaces", "tab-newline", "number"],
)
def test_create_rejects_invalid_title(body: dict[str, object]) -> None:
    assert_invalid(TaskCreate, body)


def test_title_max_length_is_measured_after_stripping() -> None:
    title = "  " + "t" * 255 + "  "

    assert parse(TaskCreate, {"title": title}).title == "t" * 255


def test_title_over_max_length_is_rejected() -> None:
    assert_invalid(TaskCreate, {"title": "t" * 256})


def test_title_length_counts_characters_not_bytes() -> None:
    assert len(parse(TaskCreate, {"title": "é" * 255}).title) == 255


@pytest.mark.parametrize("description", [None, "", "   ", "  keep  "])
def test_description_is_stored_as_given(description: str | None) -> None:
    body = {"title": "t", "description": description}

    assert parse(TaskCreate, body).description == description


def test_description_at_max_length_is_accepted() -> None:
    body = {"title": "t", "description": "🔧" * 5000}

    assert len(parse(TaskCreate, body).description or "") == 5000


def test_description_over_max_length_is_rejected() -> None:
    assert_invalid(TaskCreate, {"title": "t", "description": "d" * 5001})


@pytest.mark.parametrize("field", ["status", "priority"])
@pytest.mark.parametrize("value", ["urgent", "TODO", "HIGH", "", 3, None])
def test_create_rejects_invalid_enum_values(field: str, value: object) -> None:
    assert_invalid(TaskCreate, {"title": "t", field: value})


def test_create_rejects_unknown_fields() -> None:
    assert_invalid(TaskCreate, {"title": "t", "owner": "me"})


def test_create_rejects_client_supplied_id() -> None:
    assert_invalid(TaskCreate, {"title": "t", "id": 5})


# --- TaskPatch ------------------------------------------------------------------


def test_empty_patch_provides_nothing() -> None:
    assert parse(TaskPatch, {}).to_domain().provided() == {}


def test_patch_provides_only_sent_fields() -> None:
    update = parse(TaskPatch, {"status": "done"}).to_domain()

    assert update.provided() == {"status": TaskStatus.DONE}
    assert update.title is UNSET
    assert update.description is UNSET


def test_patch_description_null_means_clear() -> None:
    update = parse(TaskPatch, {"description": None}).to_domain()

    assert update.provided() == {"description": None}


def test_patch_strips_title() -> None:
    assert parse(TaskPatch, {"title": "  New  "}).to_domain().title == "New"


@pytest.mark.parametrize("field", ["title", "status", "priority"])
def test_patch_rejects_null_for_non_nullable_fields(field: str) -> None:
    assert_invalid(TaskPatch, {field: None})


@pytest.mark.parametrize(
    "body",
    [
        {"title": "   "},
        {"title": "t" * 256},
        {"description": "d" * 5001},
        {"status": "urgent"},
        {"priority": "critical"},
        {"owner": "me"},
    ],
)
def test_patch_rejects_invalid_values(body: dict[str, object]) -> None:
    assert_invalid(TaskPatch, body)


# --- TaskListQuery --------------------------------------------------------------


def test_list_query_defaults() -> None:
    query = TaskListQuery()

    assert (query.status, query.priority, query.limit, query.offset) == (None, None, 20, 0)


@pytest.mark.parametrize("limit", [1, 100])
def test_list_query_accepts_limit_bounds(limit: int) -> None:
    assert TaskListQuery(limit=limit).limit == limit


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"limit": 500}, {"limit": -1}, {"offset": -1}],
)
def test_list_query_rejects_out_of_range_values(params: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        TaskListQuery.model_validate(params)


# --- TaskResponse ---------------------------------------------------------------


def make_task(**overrides: object) -> Task:
    values: dict[str, object] = {
        "id": 1,
        "title": "Fix printer",
        "description": None,
        "status": TaskStatus.TODO,
        "priority": TaskPriority.MEDIUM,
        "created_at": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return Task(**values)  # type: ignore[arg-type]


def test_response_includes_null_description() -> None:
    data = TaskResponse.from_domain(make_task()).model_dump(mode="json")

    assert "description" in data
    assert data["description"] is None


def test_response_uses_string_enum_values() -> None:
    data = TaskResponse.from_domain(make_task(priority=TaskPriority.HIGH)).model_dump(
        mode="json"
    )

    assert data["status"] == "todo"
    assert data["priority"] == "high"


def test_response_timestamps_are_utc_with_z_suffix() -> None:
    plus_two = datetime(2026, 1, 1, 11, 0, 0, 123456, tzinfo=timezone(timedelta(hours=2)))

    data = TaskResponse.from_domain(
        make_task(created_at=plus_two, updated_at=plus_two)
    ).model_dump(mode="json")

    assert data["created_at"] == "2026-01-01T09:00:00.123456Z"
    assert data["updated_at"] == "2026-01-01T09:00:00.123456Z"
