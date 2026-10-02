from datetime import UTC, datetime

import pytest

from app.domain import (
    UNSET,
    InvalidTitleError,
    NewTask,
    Task,
    TaskPriority,
    TaskStatus,
    TaskUpdate,
    apply_update,
    normalize_title,
)

CREATED = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)


def make_task(**overrides: object) -> Task:
    values: dict[str, object] = {
        "id": 1,
        "title": "Fix printer",
        "description": "Paper jam on floor 2",
        "status": TaskStatus.TODO,
        "priority": TaskPriority.MEDIUM,
        "created_at": CREATED,
        "updated_at": CREATED,
    }
    values.update(overrides)
    return Task(**values)  # type: ignore[arg-type]


# --- Allowed values ---------------------------------------------------------


def test_status_values_are_exactly_the_contract_values() -> None:
    assert [s.value for s in TaskStatus] == ["todo", "in_progress", "done"]


def test_priority_values_are_exactly_the_contract_values() -> None:
    assert [p.value for p in TaskPriority] == ["low", "medium", "high"]


# --- Title rules --------------------------------------------------------------


def test_title_surrounding_whitespace_is_stripped() -> None:
    assert normalize_title("  Fix printer  ") == "Fix printer"


def test_title_inner_whitespace_is_kept() -> None:
    assert normalize_title("Fix  the printer") == "Fix  the printer"


@pytest.mark.parametrize("title", ["", "   ", "\t\n", " \t \n "])
def test_empty_or_whitespace_only_title_is_rejected(title: str) -> None:
    with pytest.raises(InvalidTitleError):
        normalize_title(title)


# --- Creation -----------------------------------------------------------------


def test_new_task_defaults() -> None:
    new = NewTask(title="Fix printer")

    assert new.description is None
    assert new.status is TaskStatus.TODO
    assert new.priority is TaskPriority.MEDIUM


def test_new_task_title_is_normalized() -> None:
    assert NewTask(title="  Fix printer  ").title == "Fix printer"


def test_new_task_with_blank_title_is_rejected() -> None:
    with pytest.raises(InvalidTitleError):
        NewTask(title="   ")


@pytest.mark.parametrize("description", ["", "   ", "  some text  "])
def test_new_task_description_is_stored_as_given(description: str) -> None:
    assert NewTask(title="t", description=description).description == description


# --- Partial updates ------------------------------------------------------------


def test_update_provided_contains_only_set_fields() -> None:
    assert TaskUpdate().provided() == {}
    assert TaskUpdate(status=TaskStatus.DONE).provided() == {"status": TaskStatus.DONE}


def test_update_title_is_normalized() -> None:
    assert TaskUpdate(title="  New title  ").title == "New title"


def test_update_with_blank_title_is_rejected() -> None:
    with pytest.raises(InvalidTitleError):
        TaskUpdate(title="\t\n")


def test_empty_update_is_a_no_op() -> None:
    task = make_task()

    result = apply_update(task, TaskUpdate(), now=LATER)

    assert result == task
    assert result.updated_at == CREATED


def test_update_with_same_values_does_not_bump_updated_at() -> None:
    task = make_task()
    update = TaskUpdate(
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
    )

    result = apply_update(task, update, now=LATER)

    assert result == task
    assert result.updated_at == CREATED


def test_title_equal_after_normalization_is_not_a_change() -> None:
    task = make_task(title="Fix printer")

    result = apply_update(task, TaskUpdate(title="  Fix printer  "), now=LATER)

    assert result.updated_at == CREATED


def test_real_change_updates_value_and_bumps_updated_at() -> None:
    task = make_task()

    result = apply_update(task, TaskUpdate(status=TaskStatus.DONE), now=LATER)

    assert result.status is TaskStatus.DONE
    assert result.updated_at == LATER


def test_update_leaves_other_fields_untouched() -> None:
    task = make_task()

    result = apply_update(task, TaskUpdate(priority=TaskPriority.HIGH), now=LATER)

    assert result.priority is TaskPriority.HIGH
    assert result.title == task.title
    assert result.description == task.description
    assert result.status == task.status
    assert result.id == task.id
    assert result.created_at == task.created_at


def test_mixed_update_with_one_real_change_bumps_updated_at() -> None:
    task = make_task()
    update = TaskUpdate(title=task.title, priority=TaskPriority.LOW)

    result = apply_update(task, update, now=LATER)

    assert result.title == task.title
    assert result.priority is TaskPriority.LOW
    assert result.updated_at == LATER


def test_description_omitted_leaves_it_unchanged() -> None:
    task = make_task(description="keep me")

    result = apply_update(task, TaskUpdate(title="Other"), now=LATER)

    assert result.description == "keep me"


def test_description_none_clears_it() -> None:
    task = make_task(description="clear me")

    result = apply_update(task, TaskUpdate(description=None), now=LATER)

    assert result.description is None
    assert result.updated_at == LATER


def test_clearing_already_empty_description_is_not_a_change() -> None:
    task = make_task(description=None)

    result = apply_update(task, TaskUpdate(description=None), now=LATER)

    assert result.updated_at == CREATED


def test_description_text_replaces_it() -> None:
    task = make_task(description="old")

    result = apply_update(task, TaskUpdate(description="new"), now=LATER)

    assert result.description == "new"
    assert result.updated_at == LATER


def test_unset_is_distinct_from_none() -> None:
    assert UNSET is not None
    assert TaskUpdate(description=None).provided() == {"description": None}
