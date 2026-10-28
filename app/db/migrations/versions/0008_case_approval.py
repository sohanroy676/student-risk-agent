"""Who approved a case and when, so nothing is sent to a student without a recorded approval.

Revision ID: 0008
Revises: 0007

Set by `advance` when a mentor approves; the notifier will refuse a case without it. Both
columns are set together or not at all. The API role's existing table grant covers them.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.cases ADD COLUMN approved_by text, ADD COLUMN approved_on date")
    op.execute(
        "ALTER TABLE app.cases ADD CONSTRAINT cases_approval_complete "
        "CHECK ((approved_by IS NULL) = (approved_on IS NULL))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app.cases DROP CONSTRAINT cases_approval_complete")
    op.execute("ALTER TABLE app.cases DROP COLUMN approved_by, DROP COLUMN approved_on")
