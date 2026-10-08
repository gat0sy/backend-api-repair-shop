from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import create_engine

from app.api import router
from app.config import Settings
from app.errors import EXCEPTION_HANDLERS


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
    exception_handlers=EXCEPTION_HANDLERS,
    # One canonical URL per resource: `/tasks/` is 404, not a redirect.
    redirect_slashes=False,
)
app.include_router(router)
