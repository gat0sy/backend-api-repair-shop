"""Task use cases: what the API can do with tasks.

The service applies the domain rules and calls the repository. It contains
no SQL and never commits: the request layer owns the transaction, so each
method runs inside the caller's transaction.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain import NewTask, Task, TaskPriority, TaskStatus, TaskUpdate, apply_update
from app.repository import TaskRepository


class TaskNotFoundError(Exception):
    """Raised when a task id doesn't exist."""

    def __init__(self, task_id: int) -> None:
        super().__init__(f"task {task_id} not found")
        self.task_id = task_id


@dataclass(frozen=True)
class TaskPage:
    """One page of a task listing. `total` counts all matches, ignoring pagination."""

    items: list[Task]
    total: int
    limit: int
    offset: int


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskService:
    def __init__(
        self, repository: TaskRepository, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._repository = repository
        self._clock = clock

    def create_task(self, new_task: NewTask) -> Task:
        return self._repository.add(new_task, now=self._clock())

    def get_task(self, task_id: int) -> Task:
        task = self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        limit: int,
        offset: int,
    ) -> TaskPage:
        """`limit` and `offset` are used as given; the API layer validates ranges."""
        items = self._repository.list_tasks(
            status=status, priority=priority, limit=limit, offset=offset
        )
        total = self._repository.count_tasks(status=status, priority=priority)
        return TaskPage(items=items, total=total, limit=limit, offset=offset)

    def update_task(self, task_id: int, update: TaskUpdate) -> Task:
        """Apply a partial update.

        The row is locked for the rest of the transaction, so a concurrent
        update of the same task waits instead of overwriting this one. If
        nothing actually changes, nothing is written and `updated_at` stays
        the same.
        """
        task = self._repository.get(task_id, for_update=True)
        if task is None:
            raise TaskNotFoundError(task_id)

        updated = apply_update(task, update, now=self._clock())
        if updated == task:
            return task

        saved = self._repository.update(updated)
        if saved is None:
            # Unreachable while the row is locked; kept so a missing row can
            # never be reported as a successful update.
            raise TaskNotFoundError(task_id)
        return saved

    def delete_task(self, task_id: int) -> None:
        if not self._repository.delete(task_id):
            raise TaskNotFoundError(task_id)
