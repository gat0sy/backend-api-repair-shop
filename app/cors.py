"""Cross-origin access for browser frontends (CORS).

Starlette's CORS middleware does the actual work. The only change: a rejected
preflight request is answered in the API's single error format (Problem
Details) instead of Starlette's plain-text "Disallowed CORS ...".
"""

from collections.abc import Sequence

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.errors import problem_response

ALLOWED_METHODS = ["GET", "POST", "PATCH", "DELETE"]
# Content-Type is needed for JSON request bodies. No credentials (cookies,
# auth headers): the API has no authentication.
ALLOWED_HEADERS = ["Content-Type"]
# Lets frontend JavaScript read the Location header of a 201 response.
EXPOSED_HEADERS = ["Location"]


class ProblemDetailsCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code != 400:
            return response
        # Starlette's body is "Disallowed CORS <what failed>", e.g. "origin, method".
        failed = bytes(response.body).decode().removeprefix("Disallowed CORS ")
        return problem_response(
            400,
            f"CORS preflight rejected: {failed} not allowed.",
            # Keep Starlette's CORS headers (e.g. the allowed methods).
            headers={
                k: v for k, v in response.headers.items() if k.startswith("access-")
            },
        )


def add_cors(app: FastAPI, origins: Sequence[str]) -> None:
    """Allow the given browser origins. With no origins, CORS stays off."""
    if not origins:
        return
    app.add_middleware(
        ProblemDetailsCORSMiddleware,
        allow_origins=list(origins),
        allow_methods=ALLOWED_METHODS,
        allow_headers=ALLOWED_HEADERS,
        expose_headers=EXPOSED_HEADERS,
    )
