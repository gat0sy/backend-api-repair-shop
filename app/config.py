from typing import Annotated
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, read from environment variables.

    A local `.env` file is also read, if present, for development convenience.
    Real environment variables take precedence over `.env`.
    """

    # `extra="ignore"`: .env may hold variables meant for other consumers
    # (e.g. TEST_DATABASE_URL for the test suite).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str


class CorsSettings(BaseSettings):
    """Which browser origins may call the API (CORS), from `CORS_ORIGINS`.

    Separate from `Settings`: CORS must be configured when the app is created
    (at import time), and that must not require `DATABASE_URL`.

    `CORS_ORIGINS` is a comma-separated list of exact origins, e.g.
    `http://localhost:3000,https://app.example.com`. Unset or empty means no
    cross-origin browser access (the default). `*` is rejected on purpose.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # NoDecode: read the raw string instead of parsing it as JSON.
    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _exact_origins_only(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            if origin == "*":
                raise ValueError(
                    "'*' (any origin) is not allowed; list each origin explicitly"
                )
            # Browsers send the bare origin (scheme://host[:port]). Anything
            # with a path, query or trailing slash would silently never match.
            parts = urlsplit(origin)
            if (
                parts.scheme not in ("http", "https")
                or not parts.netloc
                or parts.path
                or parts.query
                or parts.fragment
            ):
                raise ValueError(
                    f"{origin!r} is not an origin: use scheme://host[:port], "
                    "e.g. 'https://app.example.com' (no path or trailing slash)"
                )
        return origins
