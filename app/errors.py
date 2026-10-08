"""The single error structure: RFC 9457 Problem Details.

Every error response, whatever produced it, is converted here into:

    Content-Type: application/problem+json
    {
      "type": "about:blank",
      "title": "<HTTP status phrase>",
      "status": <HTTP status code>,
      "detail": "<human-readable explanation>",
      "errors": [{"location": ..., "field": ..., "message": ...}]
    }

`errors` is always present. It lists the individual problems for validation
errors and is empty otherwise. `type` is "about:blank" for every error, so
clients distinguish errors by `status`, as RFC 9457 specifies for that type.
"""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Any, Literal

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from app.service import TaskNotFoundError

PROBLEM_JSON = "application/problem+json"


class ErrorItem(BaseModel):
    location: Literal["body", "query", "path"]
    field: str | None
    message: str


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    errors: list[ErrorItem] = []


def problem_response(
    status: int,
    detail: str,
    errors: Sequence[ErrorItem] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    problem = Problem(
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        errors=list(errors),
    )
    return JSONResponse(
        problem.model_dump(mode="json"),
        status_code=status,
        headers=headers,
        media_type=PROBLEM_JSON,
    )


def _error_item(error: dict[str, Any]) -> ErrorItem:
    location, *path = error["loc"]
    message = error["msg"]
    # Our own ValueErrors (e.g. the title rules) arrive as "Value error, <text>";
    # keep only <text>.
    if error["type"] == "value_error":
        message = str(error["ctx"]["error"])
    # Pydantic's "Extra inputs are not permitted" is vague for API clients.
    elif error["type"] == "extra_forbidden":
        message = (
            "Unknown query parameter." if location == "query" else "Unknown field."
        )
    return ErrorItem(
        location=location,
        field=".".join(str(part) for part in path) or None,
        message=message,
    )


async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    # Unparseable JSON is a different failure from "parsed, but invalid":
    # 400, and no field-level details. The client's input is never echoed.
    if any(error["type"] == "json_invalid" for error in errors):
        return problem_response(400, "The request body is not valid JSON.")
    return problem_response(
        422,
        "The request contains invalid data.",
        [_error_item(error) for error in errors],
    )


async def _task_not_found_handler(
    request: Request, exc: TaskNotFoundError
) -> JSONResponse:
    return problem_response(404, f"Task {exc.task_id} not found.")


_HTTP_DETAILS = {
    404: "No resource exists at this URL.",
    405: "This method is not allowed for this URL.",
    415: "The request body must be JSON, sent with Content-Type: application/json.",
}


_HTTP_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


def _allowed_methods(request: Request) -> str:
    """All methods supported at this URL, for the `Allow` header of a 405.

    Starlette only lists the methods of the first route matching the path
    (e.g. just GET for /tasks/{id}), but RFC 9110 requires the full set. So
    ask the routes, for each method, whether they fully match this URL.
    """
    allowed = [
        method
        for method in _HTTP_METHODS
        if any(
            route.matches({**request.scope, "method": method})[0] is Match.FULL
            for route in request.app.routes
        )
    ]
    return ", ".join(allowed)


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    # Raised by the framework, e.g. unknown URL (404) or wrong method (405).
    detail = _HTTP_DETAILS.get(exc.status_code, str(exc.detail))
    headers = dict(exc.headers or {})
    if exc.status_code == 405:
        headers["Allow"] = _allowed_methods(request)
    return problem_response(exc.status_code, detail, headers=headers)


async def _unexpected_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    # Never expose internal details to the client. No logging here: Starlette
    # re-raises the exception after this response is sent, and the server
    # (uvicorn) logs it with the full traceback.
    return problem_response(500, "An unexpected error occurred.")


# Passed to FastAPI(exception_handlers=...). The Exception entry handles
# anything unexpected (500); the others map known errors to their status.
EXCEPTION_HANDLERS = {
    RequestValidationError: _validation_handler,
    TaskNotFoundError: _task_not_found_handler,
    StarletteHTTPException: _http_exception_handler,
    Exception: _unexpected_error_handler,
}
