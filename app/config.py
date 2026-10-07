from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, read from environment variables.

    A local `.env` file is also read, if present, for development convenience.
    Real environment variables take precedence over `.env`.
    """

    # `extra="ignore"`: .env may hold variables meant for other consumers
    # (e.g. TEST_DATABASE_URL for the test suite).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
