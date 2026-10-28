"""Case engine tables: mentor assignments, nightly bands, cases and their timeline.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

STATES = "('new', 'drafted', 'monitoring', 'in_review', 'escalated', 'resolved', 'dismissed')"
OPEN = "('new', 'drafted', 'monitoring', 'in_review', 'escalated')"

TABLES = [
    """CREATE TABLE app.mentor_assignments (
        student_id integer PRIMARY KEY REFERENCES core.students (id),
        mentor_id text NOT NULL
    )""",
    """CREATE TABLE app.risk_scores (
        student_id integer NOT NULL REFERENCES core.students (id),
        as_of date NOT NULL,
        probability double precision NOT NULL CHECK (probability >= 0 AND probability <= 1),
        band text NOT NULL CHECK (band IN ('green', 'amber', 'red')),
        PRIMARY KEY (student_id, as_of)
    )""",
    f"""CREATE TABLE app.cases (
        id bigserial PRIMARY KEY,
        student_id integer NOT NULL REFERENCES core.students (id),
        mentor_id text NOT NULL,
        state text NOT NULL CHECK (state IN {STATES}),
        band text NOT NULL CHECK (band IN ('amber', 'red')),
        probability double precision NOT NULL CHECK (probability >= 0 AND probability <= 1),
        reason text NOT NULL CHECK (reason IN ('red', 'rapid_rise')),
        cycle integer NOT NULL DEFAULT 1 CHECK (cycle >= 1),
        opened_on date NOT NULL,
        entered_on date NOT NULL,
        due_on date,
        closed_on date,
        overdue_noted boolean NOT NULL DEFAULT false
    )""",
    f"""CREATE UNIQUE INDEX ux_cases_one_open_per_student
        ON app.cases (student_id) WHERE state IN {OPEN}""",
    "CREATE INDEX ix_cases_mentor_state ON app.cases (mentor_id, state)",
    "CREATE INDEX ix_cases_opened_on ON app.cases (opened_on)",
    """CREATE TABLE app.case_events (
        id bigserial PRIMARY KEY,
        case_id bigint NOT NULL REFERENCES app.cases (id),
        on_date date NOT NULL,
        kind text NOT NULL,
        from_state text,
        to_state text,
        actor_kind text NOT NULL,
        actor_id text,
        detail jsonb NOT NULL DEFAULT '{}'::jsonb
    )""",
    "CREATE INDEX ix_case_events_case ON app.case_events (case_id, id)",
]

DROP = ["case_events", "cases", "risk_scores", "mentor_assignments"]


def upgrade() -> None:
    for ddl in TABLES:
        op.execute(ddl)


def downgrade() -> None:
    for table in DROP:
        op.execute(f"DROP TABLE app.{table}")
