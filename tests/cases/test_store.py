"""Case engine against real Postgres (skipped without TEST_DATABASE_URL; CI runs it)."""

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

from app.cases.config import CaseConfig
from app.cases.planner import Score
from app.cases.states import Action, Actor, NotAllowed, State
from app.cases.store import advance, run_night, run_timers

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")

DAY = date(2026, 3, 2)
CFG = CaseConfig()


def _alembic(*args: str) -> None:
    assert TEST_DB is not None
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": TEST_DB},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr


@pytest.fixture
def conn() -> Iterator[Connection]:
    """Students 1-6 belong to mentor m1 and 7-12 to m2, all inside one rolled-back transaction."""
    assert TEST_DB is not None
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    engine = create_engine(TEST_DB)
    try:
        with engine.begin() as setup:
            setup.execute(
                text("INSERT INTO core.terms VALUES (1, 'T', '2026-01-05', '2026-04-19')")
            )
            setup.execute(text("INSERT INTO core.sections VALUES (1, 'A', 1)"))
            for sid in range(1, 13):
                setup.execute(text("INSERT INTO core.students VALUES (:i, 1)"), {"i": sid})
                setup.execute(
                    text("INSERT INTO app.mentor_assignments VALUES (:i, :m)"),
                    {"i": sid, "m": "m1" if sid <= 6 else "m2"},
                )
        with engine.connect() as c:
            yield c
    finally:
        engine.dispose()
        _alembic("downgrade", "base")


def _scalar(conn: Connection, sql: str, **params: object) -> Any:
    return conn.execute(text(sql), params).scalar_one()


def _open_case(conn: Connection, student: int = 1) -> int:
    run_night(conn, [Score(student, 0.9)], DAY, CFG)
    return int(_scalar(conn, "SELECT id FROM app.cases WHERE student_id = :s", s=student))


def test_night_opens_cases_stores_scores_and_writes_events(conn: Connection) -> None:
    plan = run_night(conn, [Score(1, 0.9), Score(2, 0.4), Score(3, 0.1)], DAY, CFG)
    assert [c.student_id for c in plan.opened] == [1]
    bands = dict(conn.execute(text("SELECT student_id, band FROM app.risk_scores")).tuples())
    assert bands == {1: "red", 2: "amber", 3: "green"}
    row = conn.execute(text("SELECT state, due_on, mentor_id FROM app.cases")).one()
    assert (row.state, row.due_on, row.mentor_id) == ("new", DAY + timedelta(days=1), "m1")
    assert _scalar(conn, "SELECT count(*) FROM app.case_events WHERE kind = 'opened'") == 1


def test_rerunning_a_night_changes_nothing_and_never_beats_the_cap(conn: Connection) -> None:
    scores = [Score(i, 0.9 - i / 100) for i in range(1, 7)]  # all m1; cap is 3
    first = run_night(conn, scores, DAY, CFG)
    second = run_night(conn, scores, DAY, CFG)
    assert len(first.opened) == 3 and first.deferred == [4, 5, 6]
    assert second.opened == []  # the three are open now; the cap is used up for today
    assert _scalar(conn, "SELECT count(*) FROM app.cases") == 3
    assert _scalar(conn, "SELECT count(*) FROM app.risk_scores") == 6
    assert _scalar(conn, "SELECT count(*) FROM app.case_events") == 3


def test_deferred_students_are_picked_up_the_next_night(conn: Connection) -> None:
    scores = [Score(i, 0.9 - i / 100) for i in range(1, 6)]
    run_night(conn, scores, DAY, CFG)
    nxt = run_night(conn, scores[3:], DAY + timedelta(days=1), CFG)
    assert [c.student_id for c in nxt.opened] == [4, 5]


def test_yesterdays_band_gives_hysteresis_across_nights(conn: Connection) -> None:
    run_night(conn, [Score(1, 0.9)], DAY, CFG)
    plan = run_night(conn, [Score(1, 0.47)], DAY + timedelta(days=1), CFG)
    assert plan.bands[1].value == "red"
    fresh = run_night(conn, [Score(2, 0.47)], DAY + timedelta(days=1), CFG)
    assert fresh.bands[2].value == "amber"


def test_rapid_rise_uses_the_stored_score_from_a_week_ago(conn: Connection) -> None:
    run_night(conn, [Score(1, 0.20)], DAY, CFG)
    plan = run_night(conn, [Score(1, 0.36)], DAY + timedelta(days=7), CFG)
    assert [c.reason.value for c in plan.opened] == ["rapid_rise"]


def test_the_database_refuses_two_open_cases_for_one_student(conn: Connection) -> None:
    _open_case(conn)
    with pytest.raises(IntegrityError, match="ux_cases_one_open_per_student"):
        conn.execute(
            text(
                "INSERT INTO app.cases (student_id, mentor_id, state, band, probability, reason, "
                "opened_on, entered_on) VALUES (1, 'm1', 'new', 'red', 0.9, 'red', :d, :d)"
            ),
            {"d": DAY},
        )


def test_full_cycle_with_timeline(conn: Connection) -> None:
    case = _open_case(conn)
    assert advance(conn, case, Action.SAVE_PLAN, Actor.AGENT, "agent", DAY, CFG) is State.DRAFTED
    assert advance(conn, case, Action.APPROVE, Actor.MENTOR, "m1", DAY, CFG) is State.MONITORING
    assert run_timers(conn, DAY + timedelta(days=6), CFG).moved_to_review == []
    assert run_timers(conn, DAY + timedelta(days=7), CFG).moved_to_review == [case]
    end = DAY + timedelta(days=8)
    assert advance(conn, case, Action.RESOLVE, Actor.MENTOR, "m1", end, CFG) is State.RESOLVED
    row = conn.execute(
        text("SELECT state, closed_on FROM app.cases WHERE id = :i"), {"i": case}
    ).one()
    assert (row.state, row.closed_on) == ("resolved", end)
    kinds = conn.execute(text("SELECT kind FROM app.case_events ORDER BY id")).scalars().all()
    assert kinds == ["opened", "save_plan", "approve", "followup_due", "resolve"]


def test_another_mentor_cannot_act_on_the_case(conn: Connection) -> None:
    case = _open_case(conn)
    advance(conn, case, Action.SAVE_PLAN, Actor.AGENT, "agent", DAY, CFG)
    with pytest.raises(NotAllowed, match="own mentees"):
        advance(conn, case, Action.APPROVE, Actor.MENTOR, "m2", DAY, CFG)
    assert _scalar(conn, "SELECT state FROM app.cases WHERE id = :i", i=case) == "drafted"


def test_nothing_but_a_mentor_can_approve_and_nothing_changes_when_refused(
    conn: Connection,
) -> None:
    case = _open_case(conn)
    advance(conn, case, Action.SAVE_PLAN, Actor.AGENT, "agent", DAY, CFG)
    for actor in (Actor.AGENT, Actor.SYSTEM, Actor.STAFF):
        with pytest.raises(NotAllowed):
            advance(conn, case, Action.APPROVE, actor, "x", DAY, CFG)
    assert _scalar(conn, "SELECT count(*) FROM app.case_events WHERE kind = 'approve'") == 0


def test_unknown_case_raises(conn: Connection) -> None:
    with pytest.raises(LookupError):
        advance(conn, 999, Action.DISMISS, Actor.STAFF, "hod", DAY, CFG)


def test_third_cycle_escalates_automatically(conn: Connection) -> None:
    case = _open_case(conn)
    advance(conn, case, Action.SAVE_PLAN, Actor.AGENT, "agent", DAY, CFG)
    advance(conn, case, Action.APPROVE, Actor.MENTOR, "m1", DAY, CFG)
    day = DAY
    for expected in (State.MONITORING, State.ESCALATED):
        day += timedelta(days=7)
        run_timers(conn, day, CFG)
        assert advance(conn, case, Action.CONTINUE, Actor.MENTOR, "m1", day, CFG) is expected
    detail = conn.execute(
        text("SELECT detail FROM app.case_events WHERE kind = 'continue' ORDER BY id DESC LIMIT 1")
    ).scalar_one()
    assert detail == {"auto_escalated": True}
    assert _scalar(conn, "SELECT due_on IS NULL FROM app.cases WHERE id = :i", i=case) is True


def test_overdue_is_noted_once_and_changes_no_state(conn: Connection) -> None:
    case = _open_case(conn)  # due the next day
    assert run_timers(conn, DAY + timedelta(days=1), CFG).newly_overdue == []
    assert run_timers(conn, DAY + timedelta(days=2), CFG).newly_overdue == [case]
    assert run_timers(conn, DAY + timedelta(days=3), CFG).newly_overdue == []
    assert _scalar(conn, "SELECT state FROM app.cases WHERE id = :i", i=case) == "new"
    assert _scalar(conn, "SELECT count(*) FROM app.case_events WHERE kind = 'overdue'") == 1


def test_closed_case_blocks_reopening_for_the_cooldown(conn: Connection) -> None:
    case = _open_case(conn)
    advance(conn, case, Action.DISMISS, Actor.MENTOR, "m1", DAY, CFG)
    assert run_night(conn, [Score(1, 0.6)], DAY + timedelta(days=10), CFG).opened == []
    assert run_night(conn, [Score(1, 0.75)], DAY + timedelta(days=11), CFG).opened != []
    latest = int(_scalar(conn, "SELECT max(id) FROM app.cases"))
    advance(conn, latest, Action.DISMISS, Actor.STAFF, "hod", DAY + timedelta(days=11), CFG)
    assert run_night(conn, [Score(1, 0.6)], DAY + timedelta(days=39), CFG).opened != []


def test_migration_0003_downgrades_and_upgrades(conn: Connection) -> None:
    conn.rollback()
    conn.close()
    _alembic("downgrade", "0002")
    _alembic("upgrade", "head")
