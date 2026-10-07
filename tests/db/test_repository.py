from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, Engine, delete, select
from sqlalchemy.exc import DBAPIError

from app.db import tasks
from app.domain import NewTask, TaskPriority, TaskStatus, TaskUpdate, apply_update
from app.repository import TaskRepository

NOW = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)

LOCK_NOT_AVAILABLE = "55P03"


@pytest.fixture
def repo(connection: Connection) -> TaskRepository:
    return TaskRepository(connection)


# --- add / get ------------------------------------------------------------------


def test_add_returns_the_stored_task(repo: TaskRepository) -> None:
    task = repo.add(
        NewTask(title="Fix printer", description="Floor 2", priority=TaskPriority.HIGH),
        now=NOW,
    )

    assert isinstance(task.id, int)
    assert task.title == "Fix printer"
    assert task.description == "Floor 2"
    assert task.status is TaskStatus.TODO
    assert task.priority is TaskPriority.HIGH
    assert task.created_at == NOW
    assert task.updated_at == NOW


def test_get_returns_what_add_stored(repo: TaskRepository) -> None:
    added = repo.add(NewTask(title="Fix printer"), now=NOW)

    assert repo.get(added.id) == added


def test_get_missing_task_returns_none(repo: TaskRepository) -> None:
    assert repo.get(999_999) is None


def test_get_for_update_returns_the_task(repo: TaskRepository) -> None:
    added = repo.add(NewTask(title="Fix printer"), now=NOW)

    assert repo.get(added.id, for_update=True) == added


def test_get_for_update_locks_the_row(engine: Engine) -> None:
    # Needs a committed row, so a second connection can see it.
    with engine.begin() as setup:
        task_id = TaskRepository(setup).add(NewTask(title="Locked"), now=NOW).id
    try:
        with engine.connect() as first, engine.connect() as second:
            TaskRepository(first).get(task_id, for_update=True)

            lock_attempt = (
                select(tasks).where(tasks.c.id == task_id).with_for_update(nowait=True)
            )
            with pytest.raises(DBAPIError) as exc_info:
                second.execute(lock_attempt)
            assert getattr(exc_info.value.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE
    finally:
        with engine.begin() as cleanup:
            cleanup.execute(delete(tasks).where(tasks.c.id == task_id))


# --- list_tasks -----------------------------------------------------------------


def test_list_is_empty_without_tasks(repo: TaskRepository) -> None:
    assert repo.list_tasks(limit=20, offset=0) == []


def test_list_orders_newest_first(repo: TaskRepository) -> None:
    older = repo.add(NewTask(title="older"), now=NOW)
    newer = repo.add(NewTask(title="newer"), now=LATER)

    assert repo.list_tasks(limit=20, offset=0) == [newer, older]


def test_list_breaks_created_at_ties_by_id_descending(repo: TaskRepository) -> None:
    first = repo.add(NewTask(title="first"), now=NOW)
    second = repo.add(NewTask(title="second"), now=NOW)

    assert repo.list_tasks(limit=20, offset=0) == [second, first]


def test_list_filters_by_status(repo: TaskRepository) -> None:
    done = repo.add(NewTask(title="a", status=TaskStatus.DONE), now=NOW)
    repo.add(NewTask(title="b", status=TaskStatus.TODO), now=NOW)

    assert repo.list_tasks(status=TaskStatus.DONE, limit=20, offset=0) == [done]


def test_list_filters_by_priority(repo: TaskRepository) -> None:
    high = repo.add(NewTask(title="a", priority=TaskPriority.HIGH), now=NOW)
    repo.add(NewTask(title="b", priority=TaskPriority.LOW), now=NOW)

    assert repo.list_tasks(priority=TaskPriority.HIGH, limit=20, offset=0) == [high]


def test_list_combines_filters(repo: TaskRepository) -> None:
    match = repo.add(
        NewTask(title="a", status=TaskStatus.DONE, priority=TaskPriority.HIGH), now=NOW
    )
    repo.add(NewTask(title="b", status=TaskStatus.DONE, priority=TaskPriority.LOW), now=NOW)
    repo.add(NewTask(title="c", status=TaskStatus.TODO, priority=TaskPriority.HIGH), now=NOW)

    result = repo.list_tasks(
        status=TaskStatus.DONE, priority=TaskPriority.HIGH, limit=20, offset=0
    )

    assert result == [match]


def test_list_applies_limit_and_offset_after_ordering(repo: TaskRepository) -> None:
    added = [
        repo.add(NewTask(title=f"task {i}"), now=NOW + timedelta(minutes=i))
        for i in range(5)
    ]
    newest_first = list(reversed(added))

    assert repo.list_tasks(limit=2, offset=0) == newest_first[0:2]
    assert repo.list_tasks(limit=2, offset=2) == newest_first[2:4]
    assert repo.list_tasks(limit=2, offset=4) == newest_first[4:5]
    assert repo.list_tasks(limit=2, offset=5) == []


def test_list_paginates_within_filtered_results(repo: TaskRepository) -> None:
    done = [
        repo.add(NewTask(title=f"done {i}", status=TaskStatus.DONE), now=NOW + timedelta(minutes=i))
        for i in range(3)
    ]
    repo.add(NewTask(title="todo", status=TaskStatus.TODO), now=NOW + timedelta(minutes=10))

    result = repo.list_tasks(status=TaskStatus.DONE, limit=2, offset=1)

    assert result == [done[1], done[0]]


# --- count_tasks ----------------------------------------------------------------


def test_count_is_zero_without_tasks(repo: TaskRepository) -> None:
    assert repo.count_tasks() == 0


def test_count_without_filters_counts_all_tasks(repo: TaskRepository) -> None:
    for i in range(3):
        repo.add(NewTask(title=f"task {i}"), now=NOW)

    assert repo.count_tasks() == 3


def test_count_applies_the_same_filters_as_list(repo: TaskRepository) -> None:
    repo.add(NewTask(title="a", status=TaskStatus.DONE, priority=TaskPriority.HIGH), now=NOW)
    repo.add(NewTask(title="b", status=TaskStatus.DONE, priority=TaskPriority.LOW), now=NOW)
    repo.add(NewTask(title="c", status=TaskStatus.TODO, priority=TaskPriority.HIGH), now=NOW)

    assert repo.count_tasks(status=TaskStatus.DONE) == 2
    assert repo.count_tasks(priority=TaskPriority.HIGH) == 2
    assert repo.count_tasks(status=TaskStatus.DONE, priority=TaskPriority.HIGH) == 1
    assert repo.count_tasks(status=TaskStatus.IN_PROGRESS) == 0


@pytest.mark.parametrize(
    ("status", "priority"),
    [
        (None, None),
        (TaskStatus.DONE, None),
        (None, TaskPriority.HIGH),
        (TaskStatus.DONE, TaskPriority.HIGH),
    ],
)
def test_count_matches_number_of_listed_tasks(
    repo: TaskRepository, status: TaskStatus | None, priority: TaskPriority | None
) -> None:
    for s in TaskStatus:
        for p in TaskPriority:
            repo.add(NewTask(title=f"{s} {p}", status=s, priority=p), now=NOW)

    listed = repo.list_tasks(status=status, priority=priority, limit=100, offset=0)

    assert repo.count_tasks(status=status, priority=priority) == len(listed)


def test_count_ignores_pagination(repo: TaskRepository) -> None:
    for i in range(5):
        repo.add(NewTask(title=f"task {i}"), now=NOW)

    assert len(repo.list_tasks(limit=2, offset=4)) == 1
    assert repo.count_tasks() == 5


# --- update ---------------------------------------------------------------------


def test_update_persists_the_changed_task(repo: TaskRepository) -> None:
    task = repo.add(NewTask(title="Fix printer"), now=NOW)
    changed = apply_update(
        task, TaskUpdate(status=TaskStatus.DONE, description="Done"), now=LATER
    )

    returned = repo.update(changed)

    assert returned == changed
    assert repo.get(task.id) == changed


def test_update_does_not_touch_created_at(repo: TaskRepository) -> None:
    task = repo.add(NewTask(title="Fix printer"), now=NOW)

    returned = repo.update(apply_update(task, TaskUpdate(title="New"), now=LATER))

    assert returned is not None
    assert returned.created_at == NOW
    assert returned.updated_at == LATER


def test_update_can_clear_description(repo: TaskRepository) -> None:
    task = repo.add(NewTask(title="t", description="old"), now=NOW)

    returned = repo.update(apply_update(task, TaskUpdate(description=None), now=LATER))

    assert returned is not None
    assert returned.description is None


def test_update_missing_task_returns_none(repo: TaskRepository) -> None:
    task = repo.add(NewTask(title="t"), now=NOW)
    repo.delete(task.id)

    assert repo.update(task) is None


# --- delete ---------------------------------------------------------------------


def test_delete_removes_the_task(repo: TaskRepository) -> None:
    task = repo.add(NewTask(title="t"), now=NOW)

    assert repo.delete(task.id) is True
    assert repo.get(task.id) is None


def test_delete_missing_task_returns_false(repo: TaskRepository) -> None:
    assert repo.delete(999_999) is False
