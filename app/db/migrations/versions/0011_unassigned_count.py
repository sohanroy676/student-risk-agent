"""A count of students who have no mentor, for the department overview.

Revision ID: 0011
Revises: 0010

The API role cannot read `core`, so it cannot tell which students lack a mentor. This function
answers with one number and nothing else (no ids, no names). It answers only for staff and
admin; for any other role, or none, it returns NULL.
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

UP = [
    """CREATE FUNCTION app.unassigned_student_count() RETURNS bigint LANGUAGE sql STABLE
    SECURITY DEFINER SET search_path = pg_catalog
    AS $$ SELECT CASE WHEN app.request_role() IN ('staff', 'admin') THEN (
        SELECT count(*) FROM core.students s
        WHERE NOT EXISTS (SELECT 1 FROM app.mentor_assignments a WHERE a.student_id = s.id)
    ) END $$""",
    "REVOKE ALL ON FUNCTION app.unassigned_student_count() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION app.unassigned_student_count() TO app_api_role",
]

DOWN = [
    "DROP FUNCTION app.unassigned_student_count()",
]


def upgrade() -> None:
    for statement in UP:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN:
        op.execute(statement)
