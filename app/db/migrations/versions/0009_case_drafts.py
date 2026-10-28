"""Draft messages for a case: one row per version, never changed, only added to.

Revision ID: 0009
Revises: 0008

The nightly job writes version 1 from a template (source `template`); the v0.6 agent will write
its own (`agent`); a mentor's edit adds a `mentor` version. Whatever the latest version says
when the mentor approves is what the v0.6 notifier will send, so approval freezes it. Mentors
read and add drafts for their own mentees, staff read, nobody else sees them (the same audience
as the reasons). The API role cannot update or delete a draft.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

VISIBLE_CASE = "EXISTS (SELECT 1 FROM app.cases c WHERE c.id = case_drafts.case_id)"

UP = [
    """CREATE TABLE app.case_drafts (
        case_id bigint NOT NULL REFERENCES app.cases (id),
        version integer NOT NULL CHECK (version >= 1),
        source text NOT NULL CHECK (source IN ('template', 'agent', 'mentor')),
        author text NOT NULL,
        created_on date NOT NULL,
        message text NOT NULL CHECK (length(message) BETWEEN 1 AND 1000),
        PRIMARY KEY (case_id, version)
    )""",
    "GRANT SELECT, INSERT ON app.case_drafts TO app_api_role",
    "ALTER TABLE app.case_drafts ENABLE ROW LEVEL SECURITY",
    f"""CREATE POLICY drafts_read ON app.case_drafts FOR SELECT TO app_api_role
    USING (app.request_role() IN ('mentor', 'staff') AND {VISIBLE_CASE})""",
    f"""CREATE POLICY drafts_mentor_add ON app.case_drafts FOR INSERT TO app_api_role
    WITH CHECK (app.request_role() = 'mentor' AND source = 'mentor' AND {VISIBLE_CASE})""",
]

DOWN = [
    "DROP POLICY drafts_mentor_add ON app.case_drafts",
    "DROP POLICY drafts_read ON app.case_drafts",
    "DROP TABLE app.case_drafts",
]


def upgrade() -> None:
    for statement in UP:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN:
        op.execute(statement)
