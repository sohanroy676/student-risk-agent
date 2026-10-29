"""The department overview against real Postgres (skipped without TEST_DATABASE_URL; CI runs it)."""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_cases_postgres import TEST_DB, Api

from app.core.db import get_engine, scope_to_principal

pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")

# The fixture seeds open cases 1 (m1, drafted), 2 (m2, new) and 3 (m1, in_review), and a resolved
# case 4; students 1-6 exist and nobody is assigned yet.


def overview(api: Api, role: str = "staff") -> dict[str, object]:
    reply = api.get("/api/overview", "boss", role)
    assert reply.status_code == 200, reply.text
    body: dict[str, object] = reply.json()
    return body


def run(api: Api, sql: str, **params: object) -> None:
    with api.owner.begin() as conn:
        conn.execute(text(sql), params)


@pytest.mark.parametrize("role", ["staff", "admin"])
def test_counts_open_cases_by_state_band_and_mentor(api: Api, role: str) -> None:
    run(api, "UPDATE app.cases SET band = 'amber' WHERE id = 2")
    run(api, "UPDATE app.cases SET overdue_noted = true WHERE id IN (2, 3)")
    assert overview(api, role) == {
        "open_cases": 3,
        "overdue": 2,
        "by_state": {
            "drafted": 1,
            "escalated": 0,
            "in_review": 1,
            "monitoring": 0,
            "new": 1,
        },
        "by_band": {"amber": 1, "red": 2},
        "by_mentor": [
            {"mentor_id": "m1", "open": 2, "overdue": 1},
            {"mentor_id": "m2", "open": 1, "overdue": 1},
        ],
        "unassigned_students": 6,
    }


def test_closed_cases_are_not_counted(api: Api) -> None:
    run(api, "UPDATE app.cases SET state = 'resolved', closed_on = '2026-03-01' WHERE id <= 3")
    body = overview(api)
    assert body["open_cases"] == 0 and body["by_mentor"] == []
    assert body["by_state"] == dict.fromkeys(
        ("new", "drafted", "monitoring", "in_review", "escalated"), 0
    )


def test_an_empty_system_gives_zeros(api: Api) -> None:
    run(api, "DELETE FROM app.case_reasons")
    run(api, "DELETE FROM app.case_drafts")
    run(api, "DELETE FROM app.case_events")
    run(api, "DELETE FROM app.cases")
    run(api, "DELETE FROM core.students")
    body = overview(api)
    assert body["open_cases"] == 0 and body["overdue"] == 0
    assert body["by_mentor"] == [] and body["unassigned_students"] == 0


def test_unassigned_students_shrink_as_mentors_are_assigned(api: Api) -> None:
    run(api, "INSERT INTO app.mentor_assignments VALUES (1, 'm1'), (2, 'm1'), (3, 'm2')")
    assert overview(api)["unassigned_students"] == 3


def test_mentors_and_other_roles_are_refused_and_the_function_answers_them_nothing(
    api: Api,
) -> None:
    for role in ("mentor", "faculty"):
        assert api.get("/api/overview", "x", role).status_code == 403
    # even if a caller somehow reached the database function, it gives nothing outside staff/admin
    with get_engine().begin() as conn:
        scope_to_principal(conn, "m1", "mentor")
        assert conn.execute(text("SELECT app.unassigned_student_count()")).scalar() is None


def test_the_answer_has_no_names_ids_or_scores(api: Api) -> None:
    text_ = json.dumps(overview(api)).lower()
    for word in ("student_id", "probab", "score", "name", "phone"):
        assert word not in text_
    # students are only ever a count
    assert "unassigned_students" in text_


def test_the_api_role_cannot_read_students_directly(api: Api) -> None:
    with pytest.raises(DBAPIError), get_engine().begin() as conn:
        scope_to_principal(conn, "boss", "staff")
        conn.execute(text("SELECT count(*) FROM core.students"))
