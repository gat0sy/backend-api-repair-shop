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
TaskId = Annotated[int, Path(ge=1, le=MAX_TASK_ID)]

# Declared on every route without query parameters, so unknown query
# parameters are rejected there too (TaskListQuery does the same for the list).
NoQuery = Annotated[NoQueryParams, Query()]

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_json)]
)
def create_task(
    body: TaskCreate,
    services: ServicesDep,
    request: Request,
    response: Response,
    _: NoQuery,
) -> TaskResponse:
    with services.begin() as service:
        task = service.create_task(body.to_domain())
    response.headers["Location"] = request.app.url_path_for("get_task", task_id=task.id)
    return TaskResponse.from_domain(task)


@router.get("")
def list_tasks(
    query: Annotated[TaskListQuery, Query()], services: ServicesDep
) -> TaskListResponse:
    with services.begin() as service:
        page = service.list_tasks(
            status=query.status,
            priority=query.priority,
            limit=query.limit,
            offset=query.offset,
        )
    return TaskListResponse.from_domain(page)


@router.get("/{task_id}")
def get_task(task_id: TaskId, services: ServicesDep, _: NoQuery) -> TaskResponse:
    with services.begin() as service:
        task = service.get_task(task_id)
    return TaskResponse.from_domain(task)


@router.patch("/{task_id}", dependencies=[Depends(require_json)])
def update_task(
    task_id: TaskId, body: TaskPatch, services: ServicesDep, _: NoQuery
) -> TaskResponse:
    with services.begin() as service:
        task = service.update_task(task_id, body.to_domain())
    return TaskResponse.from_domain(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: TaskId, services: ServicesDep, _: NoQuery) -> None:
    with services.begin() as service:
        service.delete_task(task_id)
