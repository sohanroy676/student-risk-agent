"""Postgres side of the case engine: nightly run, state changes, timers.

Everything runs inside the caller's transaction. A case row is locked (`FOR UPDATE`) while it
changes, and every change writes a `case_events` row. Re-running a night is safe: scores are
upserted, the one-open-case index stops duplicates, and the per-mentor cap counts cases
already opened for that date.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Connection, text

from app.cases.bands import Band
from app.cases.config import CaseConfig
from app.cases.planner import History, NightPlan, Score, plan_night
from app.cases.states import OPEN_STATES, Action, Actor, NotAllowed, State, step

# How far either side of "a week ago" a stored score may be and still count as that week's.
WEEK_AGO_SLACK_DAYS = 2
OPEN_VALUES = sorted(s.value for s in OPEN_STATES)


def _event(
    conn: Connection,
    case_id: int,
    on: date,
    kind: str,
    old: State | None,
    new: State | None,
    actor: Actor,
    actor_id: str | None,
    detail: dict[str, object] | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO app.case_events "
            "(case_id, on_date, kind, from_state, to_state, actor_kind, actor_id, detail) "
            "VALUES (:case_id, :on, :kind, :old, :new, :actor, :actor_id, CAST(:detail AS jsonb))"
        ),
        {
            "case_id": case_id,
            "on": on,
            "kind": kind,
            "old": old and old.value,
            "new": new and new.value,
            "actor": actor.value,
            "actor_id": actor_id,
            "detail": json.dumps(detail or {}),
        },
    )


def _history(conn: Connection, ids: list[int], as_of: date, cfg: CaseConfig) -> dict[int, History]:
    week = as_of - timedelta(days=cfg.rise_window_days)
    previous: dict[int, str] = dict(
        conn.execute(
            text(
                "SELECT DISTINCT ON (student_id) student_id, band FROM app.risk_scores "
                "WHERE student_id = ANY(:ids) AND as_of < :as_of "
                "ORDER BY student_id, as_of DESC"
            ),
            {"ids": ids, "as_of": as_of},
        ).tuples()
    )
    earlier: dict[int, float] = dict(
        conn.execute(
            text(
                "SELECT DISTINCT ON (student_id) student_id, probability FROM app.risk_scores "
                "WHERE student_id = ANY(:ids) AND as_of <= :week AND as_of >= :floor "
                "ORDER BY student_id, as_of DESC"
            ),
            {"ids": ids, "week": week, "floor": week - timedelta(days=WEEK_AGO_SLACK_DAYS)},
        ).tuples()
    )
    open_ids = set(
        conn.execute(
            text(
                "SELECT student_id FROM app.cases WHERE student_id = ANY(:ids) AND state = ANY(:s)"
            ),
            {"ids": ids, "s": OPEN_VALUES},
        ).scalars()
    )
    closed: dict[int, date] = dict(
        conn.execute(
            text(
                "SELECT student_id, max(closed_on) FROM app.cases "
                "WHERE student_id = ANY(:ids) AND closed_on IS NOT NULL GROUP BY student_id"
            ),
            {"ids": ids},
        ).tuples()
    )
    return {
        i: History(
            previous_band=Band(previous[i]) if i in previous else None,
            probability_a_week_ago=earlier.get(i),
            has_open_case=i in open_ids,
            last_closed_on=closed.get(i),
        )
        for i in ids
    }


def run_night(
    conn: Connection, scores: Sequence[Score], as_of: date, cfg: CaseConfig | None = None
) -> NightPlan:
    """Store tonight's bands and open the cases the plan allows."""
    cfg = cfg or CaseConfig()
    ids = [s.student_id for s in scores]
    mentors: dict[int, str] = dict(
        conn.execute(
            text(
                "SELECT student_id, mentor_id FROM app.mentor_assignments "
                "WHERE student_id = ANY(:ids)"
            ),
            {"ids": ids},
        ).tuples()
    )
    opened_today: dict[str, int] = dict(
        conn.execute(
            text(
                "SELECT mentor_id, count(*) FROM app.cases "
                "WHERE opened_on = :as_of GROUP BY mentor_id"
            ),
            {"as_of": as_of},
        ).tuples()
    )
    plan = plan_night(scores, _history(conn, ids, as_of, cfg), mentors, as_of, cfg, opened_today)
    if scores:
        conn.execute(
            text(
                "INSERT INTO app.risk_scores (student_id, as_of, probability, band) "
                "VALUES (:student_id, :as_of, :probability, :band) "
                "ON CONFLICT (student_id, as_of) DO UPDATE SET "
                "probability = EXCLUDED.probability, band = EXCLUDED.band"
            ),
            [
                {
                    "student_id": s.student_id,
                    "as_of": as_of,
                    "probability": s.probability,
                    "band": plan.bands[s.student_id].value,
                }
                for s in scores
            ],
        )
    for case in plan.opened:
        case_id = conn.execute(
            text(
                "INSERT INTO app.cases (student_id, mentor_id, state, band, probability, reason, "
                "opened_on, entered_on, due_on) VALUES (:student_id, :mentor_id, 'new', :band, "
                ":probability, :reason, :on, :on, :due) ON CONFLICT DO NOTHING RETURNING id"
            ),
            {
                "student_id": case.student_id,
                "mentor_id": case.mentor_id,
                "band": case.band.value,
                "probability": case.probability,
                "reason": case.reason.value,
                "on": as_of,
                "due": as_of + timedelta(days=cfg.draft_due_days),
            },
        ).scalar_one_or_none()
        if case_id is not None:
            _event(
                conn,
                case_id,
                as_of,
                "opened",
                None,
                State.NEW,
                Actor.SYSTEM,
                None,
                {"reason": case.reason.value},
            )
    return plan


def advance(
    conn: Connection,
    case_id: int,
    action: Action,
    actor: Actor,
    actor_id: str | None,
    today: date,
    cfg: CaseConfig | None = None,
) -> State:
    """Apply one action to a case. Raises `NotAllowed`, or `LookupError` for an unknown case."""
    cfg = cfg or CaseConfig()
    row = conn.execute(
        text("SELECT state, cycle, mentor_id FROM app.cases WHERE id = :id FOR UPDATE"),
        {"id": case_id},
    ).one_or_none()
    if row is None:
        raise LookupError(f"no case {case_id}")
    if actor is Actor.MENTOR and actor_id != row.mentor_id:
        raise NotAllowed("a mentor can act only on their own mentees' cases")
    old = State(row.state)
    moved = step(old, row.cycle, action, actor, today, cfg)
    conn.execute(
        text(
            "UPDATE app.cases SET state = :state, cycle = :cycle, entered_on = :today, "
            "due_on = :due, closed_on = :closed, overdue_noted = false WHERE id = :id"
        ),
        {
            "state": moved.state.value,
            "cycle": moved.cycle,
            "today": today,
            "due": moved.due_on,
            "closed": today if moved.closed else None,
            "id": case_id,
        },
    )
    detail: dict[str, object] | None = (
        {"auto_escalated": True}
        if action is Action.CONTINUE and moved.state is State.ESCALATED
        else None
    )
    _event(conn, case_id, today, action.value, old, moved.state, actor, actor_id, detail)
    return moved.state


@dataclass(frozen=True)
class TimerResult:
    moved_to_review: list[int]
    newly_overdue: list[int]


def run_timers(conn: Connection, today: date, cfg: CaseConfig | None = None) -> TimerResult:
    """Day-7 follow-ups become reviews; cases past their due date get one `overdue` note."""
    cfg = cfg or CaseConfig()
    due = (
        conn.execute(
            text(
                "SELECT id FROM app.cases "
                "WHERE state = 'monitoring' AND due_on <= :today ORDER BY id"
            ),
            {"today": today},
        )
        .scalars()
        .all()
    )
    for case_id in due:
        advance(conn, case_id, Action.FOLLOWUP_DUE, Actor.SYSTEM, None, today, cfg)
    late = (
        conn.execute(
            text(
                "UPDATE app.cases SET overdue_noted = true "
                "WHERE state IN ('new', 'drafted', 'in_review') "
                "AND due_on < :today AND NOT overdue_noted RETURNING id, state"
            ),
            {"today": today},
        )
        .tuples()
        .all()
    )
    for case_id, state in sorted(late):
        _event(conn, case_id, today, "overdue", State(state), State(state), Actor.SYSTEM, None)
    return TimerResult(list(due), sorted(i for i, _ in late))
