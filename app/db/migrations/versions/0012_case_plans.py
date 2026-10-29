"""The agent's rationale and mentor steps for a draft, one row per agent draft version.

Revision ID: 0012
Revises: 0011

The student-facing wording lives in `app.case_drafts`; this table holds what the mentor needs
to judge it: claims (each citing the `fact_id`s they rest on) and suggested steps. Only the
agent writes plans, and only the nightly job (the table owner) does, so the API role gets
SELECT and nothing else. Mentors and staff read them, the same audience as the reasons.
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

VISIBLE_CASE = "EXISTS (SELECT 1 FROM app.cases c WHERE c.id = case_plans.case_id)"

UP = [
    """CREATE TABLE app.case_plans (
        case_id bigint NOT NULL,
        draft_version integer NOT NULL,
        rationale jsonb NOT NULL,
        steps jsonb NOT NULL,
        PRIMARY KEY (case_id, draft_version),
        FOREIGN KEY (case_id, draft_version) REFERENCES app.case_drafts (case_id, version)
    )""",
    "GRANT SELECT ON app.case_plans TO app_api_role",
    "ALTER TABLE app.case_plans ENABLE ROW LEVEL SECURITY",
    f"""CREATE POLICY plans_read ON app.case_plans FOR SELECT TO app_api_role
    USING (app.request_role() IN ('mentor', 'staff') AND {VISIBLE_CASE})""",
]

DOWN = [
    "DROP POLICY plans_read ON app.case_plans",
    "DROP TABLE app.case_plans",
]


def upgrade() -> None:
    for statement in UP:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN:
        op.execute(statement)
