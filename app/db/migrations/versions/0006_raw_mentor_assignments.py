"""Raw (all-text) landing table for the CSV connector's mentor assignments.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# table -> (columns, key), same shape as RAW_TABLES in migration 0002.
RAW_TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "mentor_assignments": (("student_id", "mentor_id"), ("student_id",)),
}


def upgrade() -> None:
    for table, (columns, key) in RAW_TABLES.items():
        cols = ", ".join(f"{c} text NOT NULL" for c in columns)
        op.execute(
            f"CREATE TABLE raw.{table} ({cols}, PRIMARY KEY ({', '.join(key)}))"  # noqa: S608
        )


def downgrade() -> None:
    for table in RAW_TABLES:
        op.execute(f"DROP TABLE raw.{table}")  # noqa: S608
