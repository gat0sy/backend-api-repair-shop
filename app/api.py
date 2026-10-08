"""HTTP routes for tasks.

Each route translates HTTP into a service call and the result back into
HTTP. No business rules live here.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from sqlalchemy import Engine

from app.repository import TaskRepository
from app.schemas import (
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

# Ids are Postgres INTEGER identity values. Anything outside 1..2^31-1 can
# never be an id, so it is rejected as invalid input (and never reaches SQL,
# where it would overflow the INTEGER parameter).
MAX_TASK_ID = 2_147_483_647
TaskId = Annotated[int, Path(ge=1, le=MAX_TASK_ID)]

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskCreate, services: ServicesDep, request: Request, response: Response
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
def get_task(task_id: TaskId, services: ServicesDep) -> TaskResponse:
    with services.begin() as service:
        task = service.get_task(task_id)
    return TaskResponse.from_domain(task)


@router.patch("/{task_id}")
def update_task(task_id: TaskId, body: TaskPatch, services: ServicesDep) -> TaskResponse:
    with services.begin() as service:
        task = service.update_task(task_id, body.to_domain())
    return TaskResponse.from_domain(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: TaskId, services: ServicesDep) -> None:
    with services.begin() as service:
        service.delete_task(task_id)
