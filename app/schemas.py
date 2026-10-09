"""Request and response schemas: the JSON shapes of the public API.

Request schemas validate untrusted input and convert it into domain objects.
Response schemas convert domain objects into JSON.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Self

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
            "Surrounding whitespace is stripped. Must be 1-255 characters "
            "after stripping."
        ),
        json_schema_extra={"minLength": 1, "maxLength": TITLE_MAX_LENGTH},
    ),
]

Description = Annotated[
    str | None,
    Field(
        max_length=DESCRIPTION_MAX_LENGTH,
        description=(
            "Up to 5000 characters, stored exactly as given (no stripping). "
            "`null` means no description."
        ),
    ),
]


def _not_nullable(schema: dict[str, Any]) -> None:
    """Document an optional field without `null` as an allowed value.

    `status: TaskStatus | None = None` means "may be omitted", but Pydantic
    documents it as accepting `null`, which clients can't actually send.
    """
    any_of = schema.pop("anyOf", None)
    if any_of:
        schema.update(next(s for s in any_of if s.get("type") != "null"))


class TaskCreate(BaseModel):
    """A new task. Only `title` is required. Unknown fields are rejected."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"title": "Fix printer"},
                {
                    "title": "Replace toner",
                    "description": "Printer on floor 2",
                    "status": "in_progress",
                    "priority": "high",
                },
            ]
        },
    )

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
    """Partial update: only the fields present in the body are considered.

    An omitted field is left unchanged. `{}` is valid and changes nothing.
    `updated_at` changes only if at least one value actually changes.
    Unknown fields are rejected.
    """

    # The `None` defaults below are never validated or applied. They only mark
    # a field as omitted. Which fields were actually sent is read from
    # `model_fields_set`. Because the declared types of `title`, `status` and
    # `priority` don't include None, an explicit `null` for them is rejected.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"status": "done"},
                {"title": "Fix printer (urgent)", "priority": "high"},
                {"description": None},
            ]
        },
    )

    title: Title = None  # type: ignore[assignment]
    description: Description = Field(
        default=None,
        description=(
            "Omit to keep the current description, `null` to clear it, "
            "or a string (up to 5000 characters, stored as given) to replace it."
        ),
    )
    status: TaskStatus = Field(default=None, description="`null` is rejected.")  # type: ignore[assignment]
    priority: TaskPriority = Field(default=None, description="`null` is rejected.")  # type: ignore[assignment]

    def to_domain(self) -> TaskUpdate:
        provided = {name: getattr(self, name) for name in self.model_fields_set}
        return TaskUpdate(**provided)


class TaskListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus | None = Field(
        default=None,
        description="Only tasks with this status.",
        json_schema_extra=_not_nullable,
    )
    priority: TaskPriority | None = Field(
        default=None,
        description="Only tasks with this priority.",
        json_schema_extra=_not_nullable,
    )
    limit: int = Field(
        default=20, ge=1, le=100, description="Maximum number of tasks to return."
    )
    offset: int = Field(
        default=0, ge=0, description="Number of matching tasks to skip first."
    )


class NoQueryParams(BaseModel):
    """For endpoints without query parameters: any query parameter is rejected."""

    model_config = ConfigDict(extra="forbid")


class TaskResponse(BaseModel):
    """A task. Every field is always present."""

    id: int = Field(description="Assigned by the server.")
    title: str
    description: str | None = Field(description="`null` means no description.")
    status: TaskStatus
    priority: TaskPriority
    created_at: datetime = Field(
        description="When the task was created. UTC, e.g. `2026-01-01T09:00:00Z`."
    )
    updated_at: datetime = Field(
        description=(
            "When a value last actually changed (equals `created_at` until then). UTC."
        )
    )

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
    """One page of tasks, newest first."""

    items: list[TaskResponse] = Field(
        description="Ordered by `created_at` descending, then `id` descending."
    )
    total: int = Field(
        description="Number of tasks matching the filters, ignoring pagination."
    )
    limit: int = Field(description="The `limit` used for this page.")
    offset: int = Field(description="The `offset` used for this page.")

    @classmethod
    def from_domain(cls, page: TaskPage) -> Self:
        return cls(
            items=[TaskResponse.from_domain(task) for task in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
