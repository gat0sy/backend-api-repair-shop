"""Core task domain: values, rules, and update semantics.

Plain Python with no framework or database imports, so these rules can be
tested in isolation and reused by every outer layer.
"""

from dataclasses import dataclass, fields, replace
from datetime import datetime
from enum import Enum, StrEnum


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InvalidTitleError(ValueError):
    """Raised when a title is empty after stripping surrounding whitespace."""


def normalize_title(title: str) -> str:
    """Strip surrounding whitespace and reject titles that end up empty."""
    normalized = title.strip()
    if not normalized:
        raise InvalidTitleError("title must not be empty or whitespace-only")
    return normalized


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class NewTask:
    """The values needed to create a task. The id and timestamps are assigned on save."""

    title: str
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM

    def __post_init__(self) -> None:
        # Frozen dataclasses block normal assignment; this is the documented way
        # to normalize a field during initialization.
        object.__setattr__(self, "title", normalize_title(self.title))


class _Unset(Enum):
    UNSET = "UNSET"


UNSET = _Unset.UNSET
"""Marks a field that was not provided in a partial update.

It is distinct from None, because `description=None` means "clear the description".
"""


@dataclass(frozen=True)
class TaskUpdate:
    """A partial update. Fields left as UNSET are not touched."""

    title: str | _Unset = UNSET
    description: str | None | _Unset = UNSET
    status: TaskStatus | _Unset = UNSET
    priority: TaskPriority | _Unset = UNSET

    def __post_init__(self) -> None:
        if self.title is not UNSET:
            object.__setattr__(self, "title", normalize_title(self.title))

    def provided(self) -> dict[str, object]:
        """Return only the fields that were explicitly provided."""
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if getattr(self, field.name) is not UNSET
        }


def apply_update(task: Task, update: TaskUpdate, now: datetime) -> Task:
    """Apply a partial update and return the resulting task.

    `updated_at` is set to `now` only if at least one value actually changes.
    If nothing changes, the original task is returned unchanged, and the
    result compares equal to the input.
    """
    changes = {
        name: value
        for name, value in update.provided().items()
        if getattr(task, name) != value
    }
    if not changes:
        return task
    return replace(task, **changes, updated_at=now)
