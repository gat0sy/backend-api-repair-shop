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

This module also provides the OpenAPI documentation of these responses.
"""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Any, Literal

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from app.service import TaskNotFoundError

PROBLEM_JSON = "application/problem+json"


class ErrorItem(BaseModel):
    """One problem found in the request (only present for 422)."""

    location: Literal["body", "query", "path"] = Field(
        description="Where the problem is: request body, query string or URL path."
    )
    field: str | None = Field(
        description=(
            "Name of the offending field or parameter, "
            "or `null` when the problem concerns the whole body."
        )
    )
    message: str = Field(description="Human-readable explanation.")


class Problem(BaseModel):
    """Error response (RFC 9457 Problem Details), sent as `application/problem+json`.

    Every error from this API has exactly these keys.
    """

    # Document `type` and `errors` as required in responses: they have
    # defaults but are always present in the JSON.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: str = Field(
        default="about:blank",
        description="Always `about:blank`: distinguish errors by `status`.",
    )
    title: str = Field(description="The HTTP status phrase, e.g. `Not Found`.")
    status: int = Field(description="The HTTP status code.")
    detail: str = Field(description="Human-readable explanation of this error.")
    errors: list[ErrorItem] = Field(
        default_factory=list,
        description="Every problem found (422 only). Empty for all other statuses.",
    )


# `detail` texts, shared by the handlers and the documentation examples.
MALFORMED_JSON = "The request body is not valid JSON."
INVALID_DATA = "The request contains invalid data."
UNEXPECTED_ERROR = "An unexpected error occurred."
_HTTP_DETAILS = {
    404: "No resource exists at this URL.",
    405: "This method is not allowed for this URL.",
    415: "The request body must be JSON, sent with Content-Type: application/json.",
}


def _problem(status: int, detail: str, errors: Sequence[ErrorItem] = ()) -> Problem:
    return Problem(
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        errors=list(errors),
    )


def problem_response(
    status: int,
    detail: str,
    errors: Sequence[ErrorItem] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        _problem(status, detail, errors).model_dump(mode="json"),
        status_code=status,
        headers=headers,
        media_type=PROBLEM_JSON,
    )


# --- Exception handlers ---------------------------------------------------------


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
        return problem_response(400, MALFORMED_JSON)
    return problem_response(422, INVALID_DATA, [_error_item(error) for error in errors])


def _not_found_detail(task_id: int) -> str:
    return f"Task {task_id} not found."


async def _task_not_found_handler(
    request: Request, exc: TaskNotFoundError
) -> JSONResponse:
    return problem_response(404, _not_found_detail(exc.task_id))


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


async def _unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never expose internal details to the client. No logging here: Starlette
    # re-raises the exception after this response is sent, and the server
    # (uvicorn) logs it with the full traceback.
    return problem_response(500, UNEXPECTED_ERROR)


# Passed to FastAPI(exception_handlers=...). The Exception entry handles
# anything unexpected (500); the others map known errors to their status.
EXCEPTION_HANDLERS = {
    RequestValidationError: _validation_handler,
    TaskNotFoundError: _task_not_found_handler,
    StarletteHTTPException: _http_exception_handler,
    Exception: _unexpected_error_handler,
}


# --- OpenAPI documentation ------------------------------------------------------

_RESPONSE_DOCS: dict[int, tuple[str, Problem]] = {
    400: ("The request body is not valid JSON.", _problem(400, MALFORMED_JSON)),
    404: ("No task exists with this id.", _problem(404, _not_found_detail(42))),
    415: (
        "The request body is not sent as `application/json`.",
        _problem(415, _HTTP_DETAILS[415]),
    ),
    422: (
        "Invalid input. `errors` lists every problem found.",
        _problem(
            422,
            INVALID_DATA,
            [
                ErrorItem(
                    location="body",
                    field="title",
                    message="title must not be empty or whitespace-only",
                ),
                ErrorItem(
                    location="query",
                    field="foo",
                    message="Unknown query parameter.",
                ),
            ],
        ),
    ),
    500: ("Unexpected server error.", _problem(500, UNEXPECTED_ERROR)),
}


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` entries for the given error statuses.

    Written by hand instead of FastAPI's `model=`, which would document them
    as `application/json` rather than `application/problem+json`.
    """
    return {
        status: {
            "description": _RESPONSE_DOCS[status][0],
            "content": {
                PROBLEM_JSON: {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                    "example": _RESPONSE_DOCS[status][1].model_dump(mode="json"),
                }
            },
        }
        for status in statuses
    }


def problem_schemas() -> dict[str, Any]:
    """`Problem` and `ErrorItem` schemas, for the OpenAPI components section.

    `problem_responses` refers to them by `$ref`, but FastAPI only registers
    models it sees via `model=`, so they're added to the document explicitly.
    """
    schema = Problem.model_json_schema(
        mode="serialization", ref_template="#/components/schemas/{model}"
    )
    definitions = schema.pop("$defs", {})
    return {"Problem": schema, **definitions}
