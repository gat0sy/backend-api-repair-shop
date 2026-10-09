"""HTTP routes for tasks.

Each route translates HTTP into a service call and the result back into
HTTP. No business rules live here.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import Engine

from app.errors import problem_responses
from app.repository import TaskRepository
from app.schemas import (
    NoQueryParams,
    TaskCreate,
    TaskListQuery,
    TaskListResponse,
    TaskPatch,
    TaskResponse,
)
from app.service import TaskService


class TaskServices:
    """Opens the request's transaction and provides a TaskService bound to it.

    Routes call `begin()` in their body. FastAPI runs a route body only after
    every path, query and body parameter has been validated, so invalid
    requests never touch the database. The transaction also ends inside the
    route, so it is committed (or rolled back) before the response is sent.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def begin(self) -> Iterator[TaskService]:
        """One transaction: commit on success, roll back on error."""
        with self._engine.begin() as connection:
            yield TaskService(TaskRepository(connection))


def get_services(request: Request) -> TaskServices:
    # No I/O here: dependencies run *before* parameter validation.
    return TaskServices(request.app.state.engine)


ServicesDep = Annotated[TaskServices, Depends(get_services)]


def require_json(request: Request) -> None:
    """Reject request bodies that aren't `application/json` with 415.

    Only headers are read (dependencies run before validation and must do no
    I/O). Parameters such as `; charset=utf-8` are allowed. Other JSON-based
    types like `application/merge-patch+json` are rejected on purpose: this API
    doesn't implement their semantics. A request with no body at all passes
    here and gets the normal 422 for the missing body.
    """
    content_type = request.headers.get("content-type")
    if content_type is None:
        has_body = (
            request.headers.get("content-length", "0") != "0"
            or "transfer-encoding" in request.headers
        )
        if not has_body:
            return
    elif content_type.split(";", 1)[0].strip().lower() == "application/json":
        return
    raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)


# Ids are Postgres INTEGER identity values. Anything outside 1..2^31-1 can
# never be an id, so it is rejected as invalid input (and never reaches SQL,
# where it would overflow the INTEGER parameter).
MAX_TASK_ID = 2_147_483_647
TaskId = Annotated[int, Path(ge=1, le=MAX_TASK_ID, description="The task's id.")]

# Declared on every route without query parameters, so unknown query
# parameters are rejected there too (TaskListQuery does the same for the list).
NoQuery = Annotated[NoQueryParams, Query()]

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_json)],
    summary="Create a task",
    responses={
        201: {
            "description": "The task was created.",
            "headers": {
                "Location": {
                    "description": "URL of the new task, e.g. `/tasks/42`.",
                    "schema": {"type": "string"},
                }
            },
        },
        **problem_responses(400, 415, 422, 500),
    },
)
def create_task(
    body: TaskCreate,
    services: ServicesDep,
    request: Request,
    response: Response,
    _: NoQuery,
) -> TaskResponse:
    """Create a task. `status` defaults to `todo` and `priority` to `medium`."""
    with services.begin() as service:
        task = service.create_task(body.to_domain())
    response.headers["Location"] = request.app.url_path_for("get_task", task_id=task.id)
    return TaskResponse.from_domain(task)


@router.get(
    "",
    summary="List tasks",
    responses=problem_responses(422, 500),
)
def list_tasks(
    query: Annotated[TaskListQuery, Query()], services: ServicesDep
) -> TaskListResponse:
    """List tasks, newest first (`created_at`, then `id`, descending).

    `status` and `priority` filters can be combined with each other and with
    pagination. Out-of-range `limit`/`offset` values are rejected, never
    clamped. If a parameter is repeated, only its **last** value is used and
    earlier values are ignored without being validated.
    """
    with services.begin() as service:
        page = service.list_tasks(
            status=query.status,
            priority=query.priority,
            limit=query.limit,
            offset=query.offset,
        )
    return TaskListResponse.from_domain(page)


@router.get(
    "/{task_id}",
    summary="Get a task",
    responses=problem_responses(404, 422, 500),
)
def get_task(task_id: TaskId, services: ServicesDep, _: NoQuery) -> TaskResponse:
    """Return one task."""
    with services.begin() as service:
        task = service.get_task(task_id)
    return TaskResponse.from_domain(task)


@router.patch(
    "/{task_id}",
    dependencies=[Depends(require_json)],
    summary="Update a task (partial)",
    responses=problem_responses(400, 404, 415, 422, 500),
)
def update_task(
    task_id: TaskId, body: TaskPatch, services: ServicesDep, _: NoQuery
) -> TaskResponse:
    """Change only the fields present in the body and return the full task.

    - Omitted field: left unchanged. `{}` is valid and changes nothing.
    - `description: null` clears the description. `null` for `title`,
      `status` or `priority` is rejected.
    - `updated_at` changes only if at least one value actually changes
      (e.g. sending the current status again leaves it untouched).

    The body is plain `application/json`; JSON Patch and JSON Merge Patch
    media types are not supported.
    """
    with services.begin() as service:
        task = service.update_task(task_id, body.to_domain())
    return TaskResponse.from_domain(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
    responses={
        204: {"description": "The task was deleted. No response body."},
        **problem_responses(404, 422, 500),
    },
)
def delete_task(task_id: TaskId, services: ServicesDep, _: NoQuery) -> None:
    """Delete a task. Deleting it again returns 404."""
    with services.begin() as service:
        service.delete_task(task_id)
