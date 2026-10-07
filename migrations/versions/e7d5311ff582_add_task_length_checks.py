"""add task length checks

Revision ID: e7d5311ff582
Revises: 5a38fe45bd61
Create Date: 2026-10-07

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e7d5311ff582'
down_revision: Union[str, Sequence[str], None] = '5a38fe45bd61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Second layer behind the request schemas. char_length counts characters,
    # not bytes. Fails if existing rows already violate a limit.
    op.create_check_constraint(
        op.f("ck_tasks_title_length"),
        "tasks",
        "char_length(title) BETWEEN 1 AND 255",
    )
    op.create_check_constraint(
        op.f("ck_tasks_description_length"),
        "tasks",
        "description IS NULL OR char_length(description) <= 5000",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_tasks_description_length"), "tasks", type_="check")
    op.drop_constraint(op.f("ck_tasks_title_length"), "tasks", type_="check")
