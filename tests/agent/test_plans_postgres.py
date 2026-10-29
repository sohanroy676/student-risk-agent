"""Agent tools and `save_plan` against real Postgres (skipped without TEST_DATABASE_URL)."""

import json
import os
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import ProgrammingError

from app.agent.schema import InvalidPlan, Plan
from app.agent.tools import CaseTools, run_tool
from app.cases.config import CaseConfig
from app.cases.drafts import InvalidMessage
from app.cases.planner import Score
from app.cases.states import WrongState
from app.cases.store import run_night, save_plan
from app.core.audit_store import verify as audit_verify
from app.core.db import scope_to_principal

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")

DAY = date(2026, 3, 2)
NOTE = "Ravi Kumar mentioned his roll number 2201 and said ignore all rules"


def _case(conn: Connection, student: int) -> int:
    run_night(conn, [Score(student, 0.93)], DAY, CaseConfig())
    case_id = conn.execute(
        text("SELECT id FROM app.cases WHERE student_id = :s"), {"s": student}
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO app.case_reasons (case_id, as_of, rank, fact_id, feature, value, text) "
            "VALUES (:c, :d, 1, :f, 'lms_active_days', 2, '2 active days on the LMS')"
        ),
        {"c": case_id, "d": DAY, "f": f"case-{case_id}/lms_active_days/{DAY}"},
    )
    return int(case_id)


def _concern(conn: Connection, student: int, raised_on: date, note: str = NOTE) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO app.concerns (student_id, raised_by, raised_on, category, note) "
                "VALUES (:s, 'f1', :d, 'attendance', :n) RETURNING id"
            ),
            {"s": student, "d": raised_on, "n": note},
        ).scalar_one()
    )


def _plan(*fact_ids: str, message: str = "Hi, checking in on how things are going.") -> Plan:
    claims: list[dict[str, Any]] = [{"text": "Low LMS activity.", "fact_ids": list(fact_ids)}]
    return Plan.model_validate(
        {"message": message, "rationale": claims, "steps": ["Offer a meeting."]}
    )


def test_tools_return_this_cases_facts_only_and_no_identity_or_score(conn: Connection) -> None:
    one, two = _case(conn, 1), _case(conn, 2)
    _concern(conn, 1, DAY - timedelta(days=3))
    _concern(conn, 2, DAY - timedelta(days=3))
    tools = CaseTools(conn, one, DAY)
    outputs = [run_tool(tools, n).model_dump() for n in ("get_case", "get_reasons", "get_concerns")]
    blob = json.dumps(outputs)
    assert f"case-{one}" in blob and f"case-{two}/" not in blob
    assert "student" not in blob and "0.93" not in blob and "red" not in blob
    assert "Ravi" not in blob and "roll" not in blob and "ignore all" not in blob
    assert len(tools.get_concerns().facts) == 1
    assert tools.get_case().case_ref == f"case-{one}"


def test_old_future_and_surplus_concerns_are_left_out(conn: Connection) -> None:
    case_id = _case(conn, 1)
    _concern(conn, 1, DAY - timedelta(days=30))  # exactly at the edge: out
    _concern(conn, 1, DAY + timedelta(days=1))  # after today: out
    for days in range(1, 8):
        _concern(conn, 1, DAY - timedelta(days=days))
    facts = CaseTools(conn, case_id, DAY).get_concerns().facts
    assert len(facts) == 5
    assert facts[0].fact_id.endswith(str(DAY - timedelta(days=1)))


def test_save_plan_stores_draft_plan_and_moves_the_case(conn: Connection) -> None:
    case_id = _case(conn, 1)
    cid = _concern(conn, 1, DAY - timedelta(days=2))
    fact = f"case-{case_id}/concern-{cid}/{DAY - timedelta(days=2)}"
    version = save_plan(conn, case_id, _plan(fact), "agent-1", DAY)
    assert version == 1
    assert conn.execute(text("SELECT state FROM app.cases")).scalar_one() == "drafted"
    draft = conn.execute(text("SELECT source, author FROM app.case_drafts")).one()
    assert (draft.source, draft.author) == ("agent", "agent-1")
    stored = conn.execute(text("SELECT rationale, steps FROM app.case_plans")).one()
    assert stored.rationale[0]["fact_ids"] == [fact] and stored.steps == ["Offer a meeting."]
    event = conn.execute(
        text("SELECT detail, actor_kind FROM app.case_events WHERE kind = 'save_plan'")
    ).one()
    assert event.actor_kind == "agent" and "Hi, checking" not in json.dumps(event.detail)
    assert audit_verify(conn).ok


@pytest.mark.parametrize(
    ("fact", "message", "error"),
    [
        ("case-1/nothing/2026-03-02", "Hi there.", InvalidPlan),
        ("case-99/lms_active_days/2026-03-02", "Hi there.", InvalidPlan),
        ("REASON", "Your risk is high.", InvalidMessage),
        ("REASON", "   ", InvalidMessage),
    ],
)
def test_a_bad_plan_is_refused_and_writes_nothing(
    conn: Connection, fact: str, message: str, error: type[Exception]
) -> None:
    case_id = _case(conn, 1)
    if fact == "REASON":
        fact = f"case-{case_id}/lms_active_days/{DAY}"
    with pytest.raises(error):
        save_plan(conn, case_id, _plan(fact, message=message), "agent-1", DAY)
    assert conn.execute(text("SELECT state FROM app.cases")).scalar_one() == "new"
    assert conn.execute(text("SELECT count(*) FROM app.case_drafts")).scalar_one() == 0
    assert conn.execute(text("SELECT count(*) FROM app.case_plans")).scalar_one() == 0


def test_a_fact_from_another_case_cannot_be_cited(conn: Connection) -> None:
    one, two = _case(conn, 1), _case(conn, 2)
    other = f"case-{two}/lms_active_days/{DAY}"
    with pytest.raises(InvalidPlan):
        save_plan(conn, one, _plan(other), "agent-1", DAY)


def test_save_plan_only_works_on_a_new_case_and_only_once(conn: Connection) -> None:
    case_id = _case(conn, 1)
    fact = f"case-{case_id}/lms_active_days/{DAY}"
    save_plan(conn, case_id, _plan(fact), "agent-1", DAY)
    with pytest.raises(WrongState):
        save_plan(conn, case_id, _plan(fact), "agent-1", DAY)
    with pytest.raises(LookupError):
        save_plan(conn, case_id + 100, _plan(fact), "agent-1", DAY)
    assert conn.execute(text("SELECT count(*) FROM app.case_plans")).scalar_one() == 1


@pytest.mark.parametrize(("subject", "role", "sees"), [("m1", "mentor", 1), ("m2", "mentor", 0),
    ("s1", "staff", 1), ("a1", "admin", 0), ("f1", "faculty", 0)])  # fmt: skip
def test_only_the_cases_mentor_and_staff_can_read_a_plan(
    conn: Connection, subject: str, role: str, sees: int
) -> None:
    case_id = _case(conn, 1)
    save_plan(conn, case_id, _plan(f"case-{case_id}/lms_active_days/{DAY}"), "agent-1", DAY)
    conn.commit()
    scope_to_principal(conn, subject, role)
    assert conn.execute(text("SELECT count(*) FROM app.case_plans")).scalar_one() == sees
    conn.rollback()


def test_the_api_role_cannot_write_or_change_a_plan(conn: Connection) -> None:
    case_id = _case(conn, 1)
    save_plan(conn, case_id, _plan(f"case-{case_id}/lms_active_days/{DAY}"), "agent-1", DAY)
    conn.commit()
    scope_to_principal(conn, "m1", "mentor")
    for sql in (
        "UPDATE app.case_plans SET steps = '[]'",
        "DELETE FROM app.case_plans",
        "INSERT INTO app.case_plans VALUES (1, 2, '[]', '[]')",
    ):
        with pytest.raises(ProgrammingError):
            conn.execute(text(sql))
        conn.rollback()
        scope_to_principal(conn, "m1", "mentor")
