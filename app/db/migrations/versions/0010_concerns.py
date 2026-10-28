"""Concerns that faculty raise about a student, for the student's mentor.

Revision ID: 0010
Revises: 0009

A concern is a note for people, not a signal: it opens no case, changes no band and decides
nothing. Faculty can add one and see only their own; a mentor sees concerns about their own
mentees (following reassignments, since the link is read from `app.mentor_assignments`); staff
see all; admin sees none. The note is free text, so it is limited in length and kept off the
audit log. The API role may change only the two acknowledgement columns, and nobody can
delete a row.
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

CATEGORIES = "('attendance', 'performance', 'wellbeing', 'behaviour', 'other')"
OWN_MENTEE = (
    "EXISTS (SELECT 1 FROM app.mentor_assignments a "
    "WHERE a.student_id = concerns.student_id AND a.mentor_id = app.request_user())"
)

UP = [
    f"""CREATE TABLE app.concerns (
        id bigserial PRIMARY KEY,
        student_id integer NOT NULL REFERENCES core.students (id),
        raised_by text NOT NULL,
        raised_on date NOT NULL,
        category text NOT NULL CHECK (category IN {CATEGORIES}),
        note text NOT NULL DEFAULT '' CHECK (length(note) <= 500),
        acknowledged_by text,
        acknowledged_on date,
        CONSTRAINT concerns_acknowledgement_complete
            CHECK ((acknowledged_by IS NULL) = (acknowledged_on IS NULL))
    )""",
    "CREATE INDEX ix_concerns_student ON app.concerns (student_id)",
    "CREATE INDEX ix_concerns_raised_by ON app.concerns (raised_by, raised_on)",
    "GRANT SELECT, INSERT ON app.concerns TO app_api_role",
    "GRANT UPDATE (acknowledged_by, acknowledged_on) ON app.concerns TO app_api_role",
    "GRANT USAGE ON SEQUENCE app.concerns_id_seq TO app_api_role",
    "ALTER TABLE app.concerns ENABLE ROW LEVEL SECURITY",
    """CREATE POLICY concerns_faculty_own ON app.concerns FOR SELECT TO app_api_role
    USING (app.request_role() = 'faculty' AND raised_by = app.request_user())""",
    f"""CREATE POLICY concerns_mentor_read ON app.concerns FOR SELECT TO app_api_role
    USING (app.request_role() = 'mentor' AND {OWN_MENTEE})""",
    """CREATE POLICY concerns_staff_read ON app.concerns FOR SELECT TO app_api_role
    USING (app.request_role() = 'staff')""",
    """CREATE POLICY concerns_faculty_raise ON app.concerns FOR INSERT TO app_api_role
    WITH CHECK (app.request_role() = 'faculty' AND raised_by = app.request_user()
        AND acknowledged_by IS NULL)""",
    f"""CREATE POLICY concerns_mentor_acknowledge ON app.concerns FOR UPDATE TO app_api_role
    USING (app.request_role() = 'mentor' AND {OWN_MENTEE})
    WITH CHECK (app.request_role() = 'mentor' AND {OWN_MENTEE})""",
    """CREATE POLICY concerns_staff_acknowledge ON app.concerns FOR UPDATE TO app_api_role
    USING (app.request_role() = 'staff') WITH CHECK (app.request_role() = 'staff')""",
]

DOWN = [
    "DROP POLICY concerns_staff_acknowledge ON app.concerns",
    "DROP POLICY concerns_mentor_acknowledge ON app.concerns",
    "DROP POLICY concerns_faculty_raise ON app.concerns",
    "DROP POLICY concerns_staff_read ON app.concerns",
    "DROP POLICY concerns_mentor_read ON app.concerns",
    "DROP POLICY concerns_faculty_own ON app.concerns",
    "DROP TABLE app.concerns",
]


def upgrade() -> None:
    for statement in UP:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN:
        op.execute(statement)
