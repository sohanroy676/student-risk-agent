"""Append-only, hash-chained audit log in the gov schema.

Revision ID: 0005
Revises: 0004

Rows are numbered by the writer (no sequence, so a rollback leaves no gap) and each row's
`prev_hash` is unique, so the database itself refuses a forked chain. Triggers refuse UPDATE,
DELETE and TRUNCATE. A superuser can still drop the trigger; the hash chain is what detects
that. Grants (INSERT and SELECT only for the application role) arrive with RBAC.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TABLE = """CREATE TABLE gov.audit_log (
    seq bigint PRIMARY KEY CHECK (seq >= 1),
    at timestamptz NOT NULL,
    actor_kind text NOT NULL CHECK (actor_kind <> ''),
    actor_id text,
    action text NOT NULL CHECK (action <> ''),
    subject_kind text NOT NULL CHECK (subject_kind <> ''),
    subject_ref text,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    prev_hash text NOT NULL UNIQUE CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
    hash text NOT NULL UNIQUE CHECK (hash ~ '^[0-9a-f]{64}$')
)"""

FUNCTION = """CREATE FUNCTION gov.audit_log_refuse_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'gov.audit_log is append-only';
END
$$"""

TRIGGERS = [
    """CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON gov.audit_log
    FOR EACH ROW EXECUTE FUNCTION gov.audit_log_refuse_change()""",
    """CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON gov.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION gov.audit_log_refuse_change()""",
]


def upgrade() -> None:
    op.execute(TABLE)
    op.execute(FUNCTION)
    for trigger in TRIGGERS:
        op.execute(trigger)


def downgrade() -> None:
    op.execute("DROP TABLE gov.audit_log")
    op.execute("DROP FUNCTION gov.audit_log_refuse_change()")
