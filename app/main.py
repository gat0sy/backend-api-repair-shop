from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine

from app.api import router
from app.config import Settings
from app.service import TaskNotFoundError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # pool_pre_ping: test pooled connections before use, so a database
    # restart doesn't surface as errors on the next requests.
    engine = create_engine(Settings().database_url, pool_pre_ping=True)
    app.state.engine = engine
    yield
    engine.dispose()


app = FastAPI(
    title="Repair Shop Task API",
    version="0.1.0",
    description="Task Management REST API.",
    lifespan=lifespan,
)
app.include_router(router)


@app.exception_handler(TaskNotFoundError)
def task_not_found_handler(request: Request, exc: TaskNotFoundError) -> JSONResponse:
    # FastAPI's default error shape for now; the single error structure
    # replaces this in Step 7.
    return JSONResponse(status_code=404, content={"detail": str(exc)})
