"""Database table definitions (SQLAlchemy Core).

This describes the schema the application expects. The schema itself is
created and changed only by Alembic migrations (see `migrations/`); a test
checks that the two stay in sync.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
)

from app.domain import TaskPriority, TaskStatus

# Deterministic constraint names, so migrations can refer to them reliably
# instead of relying on names Postgres generates.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _one_of(column: str, values: list[str]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"


tasks = Table(
    "tasks",
    metadata,
    # GENERATED ALWAYS: the database assigns ids; explicit ids are refused.
    Column("id", Integer, Identity(always=True), primary_key=True),
    # TEXT plus CHECK constraints below for length. The request schemas are the
    # primary enforcement; these CHECKs are a second layer for writes that
    # bypass the API.
    Column("title", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("priority", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(_one_of("status", [s.value for s in TaskStatus]), name="status"),
    CheckConstraint(
        _one_of("priority", [p.value for p in TaskPriority]), name="priority"
    ),
    # char_length counts characters, not bytes, matching the API contract.
    CheckConstraint("char_length(title) BETWEEN 1 AND 255", name="title_length"),
    CheckConstraint(
        "description IS NULL OR char_length(description) <= 5000",
        name="description_length",
    ),
)
