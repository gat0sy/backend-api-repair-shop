from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy import create_engine

from app.api import router
from app.config import Settings
from app.errors import EXCEPTION_HANDLERS, problem_schemas

DESCRIPTION = """
A small task management API.

**Conventions for every endpoint**

- Request and response bodies are JSON. Request bodies must be sent with
  `Content-Type: application/json` (otherwise `415`).
- Unknown body fields and unknown query parameters are rejected (`422`).
- Timestamps are UTC in ISO 8601 with a `Z` suffix, e.g. `2026-01-01T09:00:00Z`.
- URLs have no trailing slash: `/tasks/` is `404`, not a redirect.
- A method the URL doesn't support returns `405` with an `Allow` header
  listing the supported methods.

**Errors**

Every error response uses [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457)
with `Content-Type: application/problem+json` and the same keys:
`type` (always `about:blank`), `title`, `status`, `detail` and `errors`.
`errors` lists every problem found for `422` and is empty otherwise.
Distinguish errors by `status`.
"""


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
    description=DESCRIPTION,
    lifespan=lifespan,
    exception_handlers=EXCEPTION_HANDLERS,
    # One canonical URL per resource: `/tasks/` is 404, not a redirect.
    redirect_slashes=False,
)
app.include_router(router)

_generate_openapi = app.openapi


def _openapi_with_problem_schemas() -> dict[str, Any]:
    # FastAPI's own generator, plus the Problem/ErrorItem schemas that the
    # error responses refer to (see app.errors.problem_schemas).
    if app.openapi_schema is None:
        schema = _generate_openapi()
        schema["components"]["schemas"].update(problem_schemas())
    return app.openapi_schema  # type: ignore[return-value]


app.openapi = _openapi_with_problem_schemas  # type: ignore[method-assign]
