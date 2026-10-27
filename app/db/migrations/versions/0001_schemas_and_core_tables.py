"""Create schemas and the core ERP tables.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ["raw", "core", "ml", "app", "gov", "restricted"]

TABLES = [
    """CREATE TABLE core.terms (
        id integer PRIMARY KEY,
        name text NOT NULL,
        start_date date NOT NULL,
        end_date date NOT NULL CHECK (end_date > start_date)
    )""",
    """CREATE TABLE core.sections (
        id integer PRIMARY KEY,
        name text NOT NULL,
        term_id integer NOT NULL REFERENCES core.terms (id)
    )""",
    """CREATE TABLE core.courses (
        id integer PRIMARY KEY,
        code text NOT NULL UNIQUE,
        title text NOT NULL
    )""",
    """CREATE TABLE core.students (
        id integer PRIMARY KEY,
        section_id integer NOT NULL REFERENCES core.sections (id)
    )""",
    """CREATE TABLE core.enrollments (
        student_id integer NOT NULL REFERENCES core.students (id),
        course_id integer NOT NULL REFERENCES core.courses (id),
        PRIMARY KEY (student_id, course_id)
    )""",
    """CREATE TABLE core.attendance (
        student_id integer NOT NULL REFERENCES core.students (id),
        course_id integer NOT NULL REFERENCES core.courses (id),
        class_date date NOT NULL,
        present boolean NOT NULL,
        PRIMARY KEY (student_id, course_id, class_date)
    )""",
    """CREATE TABLE core.assessments (
        id integer PRIMARY KEY,
        course_id integer NOT NULL REFERENCES core.courses (id),
        title text NOT NULL,
        due_date date NOT NULL,
        max_marks numeric NOT NULL CHECK (max_marks > 0)
    )""",
    """CREATE TABLE core.marks (
        assessment_id integer NOT NULL REFERENCES core.assessments (id),
        student_id integer NOT NULL REFERENCES core.students (id),
        marks_obtained numeric CHECK (marks_obtained >= 0),
        submitted_on date,
        PRIMARY KEY (assessment_id, student_id)
    )""",
    """CREATE TABLE core.fees (
        id integer PRIMARY KEY,
        student_id integer NOT NULL REFERENCES core.students (id),
        due_date date NOT NULL,
        amount numeric NOT NULL CHECK (amount > 0),
        paid_on date
    )""",
    """CREATE TABLE core.lms_events (
        student_id integer NOT NULL REFERENCES core.students (id),
        course_id integer NOT NULL REFERENCES core.courses (id),
        occurred_at timestamp NOT NULL,
        event_type text NOT NULL
    )""",
    """CREATE TABLE restricted.student_attributes (
        student_id integer PRIMARY KEY REFERENCES core.students (id),
        gender text NOT NULL,
        category text NOT NULL
    )""",
]


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA {schema}")
    for ddl in TABLES:
        op.execute(ddl)
    op.execute("CREATE INDEX ix_attendance_date ON core.attendance (class_date)")
    op.execute("CREATE INDEX ix_lms_events_student ON core.lms_events (student_id, occurred_at)")


def downgrade() -> None:
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA {schema} CASCADE")
