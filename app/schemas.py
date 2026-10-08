"""Request and response schemas: the JSON shapes of the public API.

Request schemas validate untrusted input and convert it into domain objects.
Response schemas convert domain objects into JSON.
"""

from datetime import UTC, datetime
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_serializer

from app.domain import (
    NewTask,
    Task,
    TaskPriority,
    TaskStatus,
    TaskUpdate,
    normalize_title,
)
from app.service import TaskPage

TITLE_MAX_LENGTH = 255
DESCRIPTION_MAX_LENGTH = 5000


def _validate_title(value: str) -> str:
    # Strip first, then measure: the limit applies to the stored title.
    # Pydantic's own max_length would measure the raw input instead.
    title = normalize_title(value)
    if len(title) > TITLE_MAX_LENGTH:
        raise ValueError(f"title must be at most {TITLE_MAX_LENGTH} characters")
    return title


Title = Annotated[
    str,
    AfterValidator(_validate_title),
    Field(
        description=(
            "Surrounding whitespace is stripped. Must not be empty after stripping."
        ),
        json_schema_extra={"minLength": 1, "maxLength": TITLE_MAX_LENGTH},
    ),
]

Description = Annotated[
    str | None,
    Field(
        max_length=DESCRIPTION_MAX_LENGTH,
        description="Stored exactly as given. `null` means no description.",
    ),
]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    description: Description = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM

    def to_domain(self) -> NewTask:
        return NewTask(
            title=self.title,
            description=self.description,
            status=self.status,
            priority=self.priority,
        )


class TaskPatch(BaseModel):
    """Partial update: only the fields present in the request body are applied."""

    # The `None` defaults below are never validated or applied. They only mark
    # a field as omitted. Which fields were actually sent is read from
    # `model_fields_set`. Because the declared types of `title`, `status` and
    # `priority` don't include None, an explicit `null` for them is rejected.
    model_config = ConfigDict(extra="forbid")

    title: Title = None  # type: ignore[assignment]
    description: Description = None
    status: TaskStatus = None  # type: ignore[assignment]
    priority: TaskPriority = None  # type: ignore[assignment]

    def to_domain(self) -> TaskUpdate:
        provided = {name: getattr(self, name) for name in self.model_fields_set}
        return TaskUpdate(**provided)


class TaskListQuery(BaseModel):
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _as_utc(self, value: datetime) -> datetime:
        # Always UTC, which Pydantic serializes with a "Z" suffix.
        return value.astimezone(UTC)

    @classmethod
    def from_domain(cls, task: Task) -> Self:
        return cls(
            id=task.id,
            title=task.title,
            description=task.description,
            status=task.status,
            priority=task.priority,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_domain(cls, page: TaskPage) -> Self:
        return cls(
            items=[TaskResponse.from_domain(task) for task in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
