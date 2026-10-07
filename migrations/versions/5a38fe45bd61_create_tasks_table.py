"""create tasks table

Revision ID: 5a38fe45bd61
Revises:
Create Date: 2026-10-02 13:26:31.241353

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a38fe45bd61'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Allowed values are written out literally rather than imported from
    # app.domain: a migration is a snapshot of the schema at this revision and
    # must not change if the application code changes later.
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'done')",
            name=op.f("ck_tasks_status"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name=op.f("ck_tasks_priority"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("tasks")
