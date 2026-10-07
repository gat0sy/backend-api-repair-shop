"""Persistence for tasks: the only module that runs SQL against the tasks table.

The repository works on a connection it is given and never commits or rolls
back. The caller owns the transaction, so several repository calls (e.g. read,
then update) can run atomically.
"""

from datetime import datetime

from sqlalchemy import (
    ColumnElement,
    Connection,
    RowMapping,
    delete,
    func,
    insert,
    select,
    update,
)

from app.db import tasks
from app.domain import NewTask, Task, TaskPriority, TaskStatus


def _to_task(row: RowMapping) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=TaskStatus(row["status"]),
        priority=TaskPriority(row["priority"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _filters(
    status: TaskStatus | None, priority: TaskPriority | None
) -> list[ColumnElement[bool]]:
    """WHERE conditions shared by list_tasks and count_tasks, so they always agree."""
    conditions: list[ColumnElement[bool]] = []
    if status is not None:
        conditions.append(tasks.c.status == status.value)
    if priority is not None:
        conditions.append(tasks.c.priority == priority.value)
    return conditions


class TaskRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add(self, new_task: NewTask, now: datetime) -> Task:
        """Insert a task. The database assigns the id; both timestamps are `now`."""
        statement = (
            insert(tasks)
            .values(
                title=new_task.title,
                description=new_task.description,
                status=new_task.status.value,
                priority=new_task.priority.value,
                created_at=now,
                updated_at=now,
            )
            .returning(tasks)
        )
        return _to_task(self._connection.execute(statement).mappings().one())

    def get(self, task_id: int, *, for_update: bool = False) -> Task | None:
        """Return the task, or None if it doesn't exist.

        `for_update=True` locks the row (SELECT ... FOR UPDATE) until the
        caller's transaction ends, so a concurrent read-modify-write on the
        same task waits instead of overwriting this one's changes.
        """
        statement = select(tasks).where(tasks.c.id == task_id)
        if for_update:
            statement = statement.with_for_update()
        row = self._connection.execute(statement).mappings().one_or_none()
        return _to_task(row) if row is not None else None

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        limit: int,
        offset: int,
    ) -> list[Task]:
        """Return matching tasks, newest first (`created_at DESC, id DESC`).

        `limit` and `offset` are used as given; range validation happens at
        the API boundary.
        """
        statement = (
            select(tasks)
            .where(*_filters(status, priority))
            .order_by(tasks.c.created_at.desc(), tasks.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_to_task(row) for row in self._connection.execute(statement).mappings()]

    def count_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
    ) -> int:
        """Return how many tasks match the filters, ignoring pagination."""
        statement = (
            select(func.count()).select_from(tasks).where(*_filters(status, priority))
        )
        return self._connection.execute(statement).scalar_one()

    def update(self, task: Task) -> Task | None:
        """Write the task's mutable fields and `updated_at`. None if it doesn't exist.

        Deciding whether anything changed (and the new `updated_at`) is the
        caller's job, via `app.domain.apply_update`; this just persists the result.
        """
        statement = (
            update(tasks)
            .where(tasks.c.id == task.id)
            .values(
                title=task.title,
                description=task.description,
                status=task.status.value,
                priority=task.priority.value,
                updated_at=task.updated_at,
            )
            .returning(tasks)
        )
        row = self._connection.execute(statement).mappings().one_or_none()
        return _to_task(row) if row is not None else None

    def delete(self, task_id: int) -> bool:
        """Delete the task. Returns False if it didn't exist."""
        statement = delete(tasks).where(tasks.c.id == task_id).returning(tasks.c.id)
        return self._connection.execute(statement).one_or_none() is not None
