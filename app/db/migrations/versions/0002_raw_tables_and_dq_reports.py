"""Raw (all-text) landing tables for the CSV connector, data-quality reports, and a natural
key for LMS events so loading the same events twice cannot duplicate them.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# table -> (columns, key). Every column is text: the cleaner does the parsing.
RAW_TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "terms": (("id", "name", "start_date", "end_date"), ("id",)),
    "sections": (("id", "name", "term_id"), ("id",)),
    "courses": (("id", "code", "title"), ("id",)),
    "students": (("id", "section_id"), ("id",)),
    "enrollments": (("student_id", "course_id"), ("student_id", "course_id")),
    "attendance": (
        ("student_id", "course_id", "class_date", "present"),
        ("student_id", "course_id", "class_date"),
    ),
    "assessments": (("id", "course_id", "title", "due_date", "max_marks"), ("id",)),
    "marks": (
        ("assessment_id", "student_id", "marks_obtained", "submitted_on"),
        ("assessment_id", "student_id"),
    ),
    "fees": (("id", "student_id", "due_date", "amount", "paid_on"), ("id",)),
    "lms_events": (
        ("student_id", "course_id", "occurred_at", "event_type"),
        ("student_id", "course_id", "occurred_at", "event_type"),
    ),
    "student_attributes": (("student_id", "gender", "category"), ("student_id",)),
}


def upgrade() -> None:
    for table, (columns, key) in RAW_TABLES.items():
        cols = ", ".join(f"{c} text NOT NULL" for c in columns)
        op.execute(
            f"CREATE TABLE raw.{table} ({cols}, PRIMARY KEY ({', '.join(key)}))"  # noqa: S608
        )
    op.execute(
        """CREATE TABLE raw.dq_reports (
            run_date date NOT NULL,
            source text NOT NULL,
            status text NOT NULL CHECK (status IN ('ok', 'warn', 'fail')),
            report jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (run_date, source)
        )"""
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_lms_events_key "
        "ON core.lms_events (student_id, course_id, occurred_at, event_type)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX core.ux_lms_events_key")
    op.execute("DROP TABLE raw.dq_reports")
    for table in reversed(list(RAW_TABLES)):
        op.execute(f"DROP TABLE raw.{table}")
