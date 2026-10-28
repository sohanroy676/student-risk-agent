"""Row-level security for the API: who may read or change which case rows, and nothing more.

Revision ID: 0007
Revises: 0006

The API runs each request as `app_api_role` (see `app.core.db.scope_to_principal`), which owns
nothing and has only the grants below. Policies read two transaction-local settings, `app.role`
and `app.user_id`; if either is missing or unknown no row matches, so an unscoped request sees
nothing. A mentor sees and changes only their own mentees' cases, staff and admin see all, and
faculty see none. Table owners (migrations, the nightly job) are not subject to these policies.

The API role has no access to `core`, `raw`, `restricted`, `ml`, or `app.risk_scores`. It can
append to the audit log but only an admin can read it; `gov.audit_head()` lets any writer find
the end of the chain without being able to read the log. The role is created if it is missing
and is left in place on downgrade, because roles belong to the whole server, not one database.
Creating it needs a login with CREATEROLE.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

OVERSIGHT = "app.request_role() IN ('staff', 'admin')"
OWN = "app.request_role() = 'mentor' AND mentor_id = app.request_user()"
VISIBLE_CASE = "EXISTS (SELECT 1 FROM app.cases c WHERE c.id = {table}.case_id)"

UP = [
    """DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_api_role') THEN
            CREATE ROLE app_api_role NOLOGIN;
        END IF;
    END $$""",
    """CREATE FUNCTION app.request_user() RETURNS text LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('app.user_id', true), '') $$""",
    """CREATE FUNCTION app.request_role() RETURNS text LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('app.role', true), '') $$""",
    """CREATE FUNCTION gov.audit_head() RETURNS TABLE (seq bigint, hash text)
    LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, gov
    AS $$ SELECT l.seq, l.hash FROM gov.audit_log l ORDER BY l.seq DESC LIMIT 1 $$""",
    "REVOKE ALL ON FUNCTION gov.audit_head() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION gov.audit_head() TO app_api_role",
    "GRANT USAGE ON SCHEMA app, gov TO app_api_role",
    "GRANT SELECT, UPDATE ON app.cases TO app_api_role",
    "GRANT SELECT, INSERT ON app.case_events TO app_api_role",
    "GRANT USAGE ON SEQUENCE app.case_events_id_seq TO app_api_role",
    "GRANT SELECT ON app.case_reasons TO app_api_role",
    "GRANT SELECT, INSERT, UPDATE ON app.mentor_assignments TO app_api_role",
    "GRANT SELECT, INSERT ON gov.audit_log TO app_api_role",
    "ALTER TABLE app.cases ENABLE ROW LEVEL SECURITY",
    f"""CREATE POLICY cases_mentor ON app.cases FOR ALL TO app_api_role
    USING ({OWN}) WITH CHECK ({OWN})""",
    f"""CREATE POLICY cases_oversight ON app.cases FOR ALL TO app_api_role
    USING ({OVERSIGHT}) WITH CHECK ({OVERSIGHT})""",
    "ALTER TABLE app.case_events ENABLE ROW LEVEL SECURITY",
    f"""CREATE POLICY events_follow_case ON app.case_events FOR ALL TO app_api_role
    USING ({VISIBLE_CASE.format(table="case_events")})
    WITH CHECK ({VISIBLE_CASE.format(table="case_events")})""",
    "ALTER TABLE app.case_reasons ENABLE ROW LEVEL SECURITY",
    f"""CREATE POLICY reasons_follow_case ON app.case_reasons FOR SELECT TO app_api_role
    USING ({VISIBLE_CASE.format(table="case_reasons")})""",
    "ALTER TABLE app.mentor_assignments ENABLE ROW LEVEL SECURITY",
    f"""CREATE POLICY assignments_mentor_read ON app.mentor_assignments FOR SELECT TO app_api_role
    USING ({OWN})""",
    f"""CREATE POLICY assignments_oversight_read ON app.mentor_assignments FOR SELECT
    TO app_api_role USING ({OVERSIGHT})""",
    """CREATE POLICY assignments_admin_write ON app.mentor_assignments FOR ALL TO app_api_role
    USING (app.request_role() = 'admin') WITH CHECK (app.request_role() = 'admin')""",
    "ALTER TABLE gov.audit_log ENABLE ROW LEVEL SECURITY",
    """CREATE POLICY audit_admin_read ON gov.audit_log FOR SELECT TO app_api_role
    USING (app.request_role() = 'admin')""",
    "CREATE POLICY audit_append ON gov.audit_log FOR INSERT TO app_api_role WITH CHECK (true)",
]

DOWN = [
    "DROP POLICY audit_append ON gov.audit_log",
    "DROP POLICY audit_admin_read ON gov.audit_log",
    "ALTER TABLE gov.audit_log DISABLE ROW LEVEL SECURITY",
    "DROP POLICY assignments_admin_write ON app.mentor_assignments",
    "DROP POLICY assignments_oversight_read ON app.mentor_assignments",
    "DROP POLICY assignments_mentor_read ON app.mentor_assignments",
    "ALTER TABLE app.mentor_assignments DISABLE ROW LEVEL SECURITY",
    "DROP POLICY reasons_follow_case ON app.case_reasons",
    "ALTER TABLE app.case_reasons DISABLE ROW LEVEL SECURITY",
    "DROP POLICY events_follow_case ON app.case_events",
    "ALTER TABLE app.case_events DISABLE ROW LEVEL SECURITY",
    "DROP POLICY cases_oversight ON app.cases",
    "DROP POLICY cases_mentor ON app.cases",
    "ALTER TABLE app.cases DISABLE ROW LEVEL SECURITY",
    "REVOKE ALL ON app.cases, app.case_events, app.case_reasons, app.mentor_assignments "
    "FROM app_api_role",
    "REVOKE ALL ON gov.audit_log FROM app_api_role",
    "REVOKE ALL ON SEQUENCE app.case_events_id_seq FROM app_api_role",
    "REVOKE ALL ON SCHEMA app, gov FROM app_api_role",
    "DROP FUNCTION gov.audit_head()",
    "DROP FUNCTION app.request_role()",
    "DROP FUNCTION app.request_user()",
]


def upgrade() -> None:
    for statement in UP:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN:
        op.execute(statement)
