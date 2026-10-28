"""Reasons behind an open case, one set per night: mentor-only, never shown to students.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE app.case_reasons (
            case_id bigint NOT NULL REFERENCES app.cases (id),
            as_of date NOT NULL,
            rank smallint NOT NULL CHECK (rank >= 1),
            fact_id text NOT NULL,
            feature text NOT NULL,
            value double precision NOT NULL,
            text text NOT NULL,
            PRIMARY KEY (case_id, as_of, rank)
        )"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE app.case_reasons")
