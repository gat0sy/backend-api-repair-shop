from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection

from app.domain import NewTask, Task, TaskPriority, TaskStatus, TaskUpdate
from app.repository import TaskRepository
from app.service import TaskNotFoundError, TaskPage, TaskService, utc_now

START = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
MISSING_ID = 999_999


class FakeClock:
    """A clock the test controls: returns `now` until `advance` is called."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta = timedelta(hours=1)) -> datetime:
        self.now += delta
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def repo(connection: Connection) -> TaskRepository:
    return TaskRepository(connection)


@pytest.fixture
def service(repo: TaskRepository, clock: FakeClock) -> TaskService:
    return TaskService(repo, clock=clock)


# --- clock ----------------------------------------------------------------------


def test_default_clock_is_timezone_aware_utc() -> None:
    now = utc_now()

    assert now.tzinfo is UTC


# --- create ---------------------------------------------------------------------


def test_create_stamps_both_timestamps_with_the_clock(service: TaskService) -> None:
    task = service.create_task(NewTask(title="Fix printer"))

    assert task.created_at == START
    assert task.updated_at == START


def test_create_applies_domain_defaults(service: TaskService) -> None:
    task = service.create_task(NewTask(title="  Fix printer  "))

    assert task.title == "Fix printer"
    assert task.description is None
    assert task.status is TaskStatus.TODO
    assert task.priority is TaskPriority.MEDIUM


def test_created_task_can_be_retrieved(service: TaskService) -> None:
    created = service.create_task(NewTask(title="Fix printer"))

    assert service.get_task(created.id) == created


# --- get ------------------------------------------------------------------------


def test_get_missing_task_raises_not_found(service: TaskService) -> None:
    with pytest.raises(TaskNotFoundError) as exc_info:
        service.get_task(MISSING_ID)

    assert exc_info.value.task_id == MISSING_ID


# --- list -----------------------------------------------------------------------


def test_list_returns_a_page_with_total(service: TaskService, clock: FakeClock) -> None:
    created = []
    for i in range(5):
        created.append(service.create_task(NewTask(title=f"task {i}")))
        clock.advance()

    page = service.list_tasks(limit=2, offset=1)

    newest_first = list(reversed(created))
    assert page == TaskPage(items=newest_first[1:3], total=5, limit=2, offset=1)


def test_list_total_respects_filters(service: TaskService) -> None:
    done = service.create_task(NewTask(title="a", status=TaskStatus.DONE))
    service.create_task(NewTask(title="b", status=TaskStatus.TODO))

    page = service.list_tasks(status=TaskStatus.DONE, limit=20, offset=0)

    assert page.items == [done]
    assert page.total == 1


def test_list_total_is_kept_when_offset_is_past_the_end(service: TaskService) -> None:
    service.create_task(NewTask(title="only"))

    page = service.list_tasks(limit=20, offset=10)

    assert page.items == []
    assert page.total == 1


# --- update ---------------------------------------------------------------------


def test_update_changes_value_and_bumps_updated_at(
    service: TaskService, clock: FakeClock
) -> None:
    task = service.create_task(NewTask(title="Fix printer"))
    later = clock.advance()

    updated = service.update_task(task.id, TaskUpdate(status=TaskStatus.DONE))

    assert updated.status is TaskStatus.DONE
    assert updated.updated_at == later
    assert updated.created_at == START
    assert service.get_task(task.id) == updated


def test_empty_update_is_a_no_op(service: TaskService, clock: FakeClock) -> None:
    task = service.create_task(NewTask(title="Fix printer"))
    clock.advance()

    assert service.update_task(task.id, TaskUpdate()) == task
    assert service.get_task(task.id).updated_at == START


def test_update_without_effective_change_keeps_updated_at(
    service: TaskService, clock: FakeClock
) -> None:
    task = service.create_task(NewTask(title="Fix printer", description="Floor 2"))
    clock.advance()

    result = service.update_task(
        task.id, TaskUpdate(title="  Fix printer  ", description="Floor 2")
    )

    assert result == task
    assert service.get_task(task.id).updated_at == START


def test_update_without_effective_change_does_not_write(
    service: TaskService, repo: TaskRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = service.create_task(NewTask(title="Fix printer"))

    def fail_on_write(task: Task) -> Task | None:
        raise AssertionError("repository.update must not be called for a no-op")

    monkeypatch.setattr(repo, "update", fail_on_write)

    assert service.update_task(task.id, TaskUpdate(title="Fix printer")) == task


def test_update_locks_the_row_before_reading(
    service: TaskService, repo: TaskRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = service.create_task(NewTask(title="Fix printer"))
    calls: list[bool] = []
    original_get = repo.get

    def recording_get(task_id: int, *, for_update: bool = False) -> Task | None:
        calls.append(for_update)
        return original_get(task_id, for_update=for_update)

    monkeypatch.setattr(repo, "get", recording_get)

    service.update_task(task.id, TaskUpdate(status=TaskStatus.DONE))

    assert calls == [True]


def test_update_can_clear_description(service: TaskService) -> None:
    task = service.create_task(NewTask(title="t", description="old"))

    updated = service.update_task(task.id, TaskUpdate(description=None))

    assert updated.description is None


def test_update_missing_task_raises_not_found(service: TaskService) -> None:
    with pytest.raises(TaskNotFoundError) as exc_info:
        service.update_task(MISSING_ID, TaskUpdate(status=TaskStatus.DONE))

    assert exc_info.value.task_id == MISSING_ID


def test_empty_update_of_missing_task_still_raises_not_found(
    service: TaskService,
) -> None:
    with pytest.raises(TaskNotFoundError):
        service.update_task(MISSING_ID, TaskUpdate())


# --- delete ---------------------------------------------------------------------


def test_delete_removes_the_task(service: TaskService) -> None:
    task = service.create_task(NewTask(title="t"))

    service.delete_task(task.id)

    with pytest.raises(TaskNotFoundError):
        service.get_task(task.id)


def test_delete_missing_task_raises_not_found(service: TaskService) -> None:
    with pytest.raises(TaskNotFoundError) as exc_info:
        service.delete_task(MISSING_ID)

    assert exc_info.value.task_id == MISSING_ID


def test_deleting_twice_raises_not_found_the_second_time(service: TaskService) -> None:
    task = service.create_task(NewTask(title="t"))
    service.delete_task(task.id)

    with pytest.raises(TaskNotFoundError):
        service.delete_task(task.id)
