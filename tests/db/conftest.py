from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, Engine, create_engine, make_url

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
START = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


class DatabaseTestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    test_database_url: str


def alembic_config(connection: Connection) -> Config:
    """Alembic config that runs migrations on the given connection."""
    config = Config(ALEMBIC_INI)
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = DatabaseTestSettings().test_database_url
    # The schema is dropped below; refuse to touch anything that isn't
    # clearly a test database.
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        raise RuntimeError(
            "TEST_DATABASE_URL must point to a database ending in '_test', "
            f"got {database!r}"
        )

    engine = create_engine(url)
    # Start every test session from an empty schema, built by the migrations.
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
        command.upgrade(alembic_config(connection), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """A connection whose changes are rolled back after the test."""
    with engine.connect() as connection:
        yield connection
        connection.rollback()


class FakeClock:
    """A clock the test controls: returns `now` until `advance` is called."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta = timedelta(hours=1)) -> datetime:
        self.now += delta
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)
