from datetime import UTC, datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, Executable, RowMapping, inspect, insert
from sqlalchemy.exc import DBAPIError

from app.db import metadata, tasks
from app.domain import TaskPriority, TaskStatus

from .conftest import alembic_config

NOW = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

# PostgreSQL error codes (SQLSTATE).
NOT_NULL_VIOLATION = "23502"
CHECK_VIOLATION = "23514"
GENERATED_ALWAYS = "428C9"


def valid_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "title": "Fix printer",
        "status": "todo",
        "priority": "medium",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return values


def insert_task(connection: Connection, **overrides: object) -> RowMapping:
    statement = insert(tasks).values(**valid_values(**overrides)).returning(tasks)
    return connection.execute(statement).mappings().one()


def assert_rejected(connection: Connection, statement: Executable, sqlstate: str) -> None:
    with pytest.raises(DBAPIError) as exc_info:
        connection.execute(statement)
    assert getattr(exc_info.value.orig, "sqlstate", None) == sqlstate


# --- Migrations -----------------------------------------------------------------


def test_migrations_downgrade_and_upgrade_cleanly(engine: Engine) -> None:
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
        assert not inspect(connection).has_table("tasks")

        command.upgrade(alembic_config(connection), "head")
        assert inspect(connection).has_table("tasks")


def test_migrations_match_table_definitions(connection: Connection) -> None:
    # Fails if app/db.py and the migrations drift apart (columns, types,
    # nullability). Alembic does not compare CHECK constraints; those are
    # covered by the behavior tests below.
    differences = compare_metadata(MigrationContext.configure(connection), metadata)

    assert differences == []


def test_check_constraint_names_match_table_definitions(connection: Connection) -> None:
    in_database = {c["name"] for c in inspect(connection).get_check_constraints("tasks")}

    assert in_database == {
        "ck_tasks_status",
        "ck_tasks_priority",
        "ck_tasks_title_length",
        "ck_tasks_description_length",
    }


# --- Identity -------------------------------------------------------------------


def test_database_assigns_increasing_ids(connection: Connection) -> None:
    first = insert_task(connection)
    second = insert_task(connection)

    assert isinstance(first["id"], int)
    assert second["id"] > first["id"]


def test_explicit_id_is_rejected(connection: Connection) -> None:
    statement = insert(tasks).values(id=12345, **valid_values())

    assert_rejected(connection, statement, GENERATED_ALWAYS)


# --- Allowed values -------------------------------------------------------------


@pytest.mark.parametrize("status", list(TaskStatus))
def test_every_domain_status_is_accepted(connection: Connection, status: TaskStatus) -> None:
    assert insert_task(connection, status=status.value)["status"] == status.value


@pytest.mark.parametrize("priority", list(TaskPriority))
def test_every_domain_priority_is_accepted(
    connection: Connection, priority: TaskPriority
) -> None:
    assert insert_task(connection, priority=priority.value)["priority"] == priority.value


@pytest.mark.parametrize("column", ["status", "priority"])
def test_unknown_enum_value_is_rejected(connection: Connection, column: str) -> None:
    statement = insert(tasks).values(**valid_values(**{column: "urgent"}))

    assert_rejected(connection, statement, CHECK_VIOLATION)


# --- Nullability ----------------------------------------------------------------


@pytest.mark.parametrize(
    "column", ["title", "status", "priority", "created_at", "updated_at"]
)
def test_required_column_rejects_null(connection: Connection, column: str) -> None:
    statement = insert(tasks).values(**valid_values(**{column: None}))

    assert_rejected(connection, statement, NOT_NULL_VIOLATION)


def test_description_may_be_null(connection: Connection) -> None:
    assert insert_task(connection, description=None)["description"] is None


# --- Column types ---------------------------------------------------------------


def test_timestamps_keep_the_exact_instant(connection: Connection) -> None:
    # An aware datetime in another offset must come back as the same instant.
    plus_two = datetime(2026, 1, 1, 11, 0, tzinfo=timezone(timedelta(hours=2)))

    row = insert_task(connection, created_at=plus_two, updated_at=plus_two)

    assert row["created_at"] == NOW
    assert row["created_at"].tzinfo is not None


# --- Length limits --------------------------------------------------------------
# Second layer behind the request schemas: 255 for title, 5000 for description.


def test_title_at_max_length_is_accepted(connection: Connection) -> None:
    assert len(insert_task(connection, title="t" * 255)["title"]) == 255


@pytest.mark.parametrize("title", ["", "t" * 256])
def test_title_outside_length_limits_is_rejected(connection: Connection, title: str) -> None:
    statement = insert(tasks).values(**valid_values(title=title))

    assert_rejected(connection, statement, CHECK_VIOLATION)


def test_description_at_max_length_is_accepted(connection: Connection) -> None:
    row = insert_task(connection, description="d" * 5000)

    assert len(row["description"]) == 5000


def test_description_over_max_length_is_rejected(connection: Connection) -> None:
    statement = insert(tasks).values(**valid_values(description="d" * 5001))

    assert_rejected(connection, statement, CHECK_VIOLATION)


def test_length_limits_count_characters_not_bytes(connection: Connection) -> None:
    # "é" is 2 bytes and "🔧" is 4 bytes in UTF-8, but each is one character.
    row = insert_task(connection, title="é" * 255, description="🔧" * 5000)

    assert len(row["title"]) == 255
    assert len(row["description"]) == 5000
