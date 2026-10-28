"""Postgres side of the case engine: nightly run, state changes, timers.

Everything runs inside the caller's transaction. A case row is locked (`FOR UPDATE`) while it
changes, and every change writes a `case_events` row and a hash-chained audit entry (which
refers to the case by `case-<id>` and carries no scores or bands). Re-running a night is safe:
scores are upserted, the one-open-case index stops duplicates, and the per-mentor cap counts
cases already opened for that date.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.cases.bands import Band
from app.cases.config import CaseConfig
from app.cases.drafts import check_message, template_message
from app.cases.planner import History, NightPlan, Score, plan_night
from app.cases.states import OPEN_STATES, Action, Actor, State, WrongActor, WrongState, step
from app.core import audit_store as audit

# How far either side of "a week ago" a stored score may be and still count as that week's.
WEEK_AGO_SLACK_DAYS = 2
OPEN_VALUES = sorted(s.value for s in OPEN_STATES)
TEMPLATE_AUTHOR = "template"


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
    audit.append(
        conn,
        actor_kind=actor.value,
        actor_id=actor_id,
        action=f"case.{kind}",
        subject_kind="case",
        subject_ref=f"case-{case_id}",
        detail={
            "on": on.isoformat(),
            "from": old and old.value,
            "to": new and new.value,
            **(detail or {}),
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
        )
        .tuples()
        .all()
    )
    earlier: dict[int, float] = dict(
        conn.execute(
            text(
                "SELECT DISTINCT ON (student_id) student_id, probability FROM app.risk_scores "
                "WHERE student_id = ANY(:ids) AND as_of <= :week AND as_of >= :floor "
                "ORDER BY student_id, as_of DESC"
            ),
            {"ids": ids, "week": week, "floor": week - timedelta(days=WEEK_AGO_SLACK_DAYS)},
        )
        .tuples()
        .all()
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
        )
        .tuples()
        .all()
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
        )
        .tuples()
        .all()
    )
    opened_today: dict[str, int] = dict(
        conn.execute(
            text(
                "SELECT mentor_id, count(*) FROM app.cases "
                "WHERE opened_on = :as_of GROUP BY mentor_id"
            ),
            {"as_of": as_of},
        )
        .tuples()
        .all()
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
    """Apply one action to a case. Raises `WrongActor` or `WrongState` (both `NotAllowed`), or
    `LookupError` for an unknown case. Approving records who approved and when."""
    cfg = cfg or CaseConfig()
    row = conn.execute(
        text("SELECT state, cycle, mentor_id FROM app.cases WHERE id = :id FOR UPDATE"),
        {"id": case_id},
    ).one_or_none()
    if row is None:
        raise LookupError(f"no case {case_id}")
    if actor is Actor.MENTOR and actor_id != row.mentor_id:
        raise WrongActor("a mentor can act only on their own mentees' cases")
    old = State(row.state)
    moved = step(old, row.cycle, action, actor, today, cfg)
    conn.execute(
        text(
            "UPDATE app.cases SET state = :state, cycle = :cycle, entered_on = :today, "
            "due_on = :due, closed_on = :closed, overdue_noted = false, "
            "approved_by = CASE WHEN :approving THEN :actor_id ELSE approved_by END, "
            "approved_on = CASE WHEN :approving THEN CAST(:today AS date) ELSE approved_on END "
            "WHERE id = :id"
        ),
        {
            "state": moved.state.value,
            "cycle": moved.cycle,
            "today": today,
            "due": moved.due_on,
            "closed": today if moved.closed else None,
            "approving": action is Action.APPROVE,
            "actor_id": actor_id,
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


def _add_draft(
    conn: Connection, case_id: int, source: str, author: str, message: str, today: date
) -> int:
    """Add the next version of a case's draft and return its number."""
    return int(
        conn.execute(
            text(
                "INSERT INTO app.case_drafts "
                "(case_id, version, source, author, created_on, message) "
                "SELECT :case, coalesce(max(version), 0) + 1, :source, :author, :today, :message "
                "FROM app.case_drafts WHERE case_id = :case RETURNING version"
            ),
            {
                "case": case_id,
                "source": source,
                "author": author,
                "today": today,
                "message": message,
            },
        ).scalar_one()
    )


def draft_new_cases(conn: Connection, today: date, cfg: CaseConfig | None = None) -> list[int]:
    """Give every new case its template draft and move it to `drafted`.

    This is the template fallback of the drafting step: it saves the plan as the agent actor
    (author `template`) until the v0.6 agent writes real drafts. Nothing is sent; a mentor must
    still approve. Cases already drafted are left alone, so a re-run changes nothing.
    """
    found = conn.execute(
        text("SELECT id, cycle FROM app.cases WHERE state = 'new' ORDER BY id")
    ).tuples()
    new_cases = list(found)
    for case_id, cycle in new_cases:
        _add_draft(conn, case_id, "template", TEMPLATE_AUTHOR, template_message(cycle), today)
        advance(conn, case_id, Action.SAVE_PLAN, Actor.AGENT, TEMPLATE_AUTHOR, today, cfg)
    return [case_id for case_id, _ in new_cases]


def edit_draft(conn: Connection, case_id: int, message: str, mentor_id: str, today: date) -> int:
    """Add a mentor's wording as the next draft version and return the version now current.

    Only the case's own mentor, and only while the case is `drafted`: once approved the text is
    frozen. Raises `LookupError` (unknown or hidden case), `WrongActor`, `WrongState` or
    `InvalidMessage`. Saving the wording the draft already has changes nothing.
    """
    row = conn.execute(
        text("SELECT state, mentor_id FROM app.cases WHERE id = :id FOR UPDATE"), {"id": case_id}
    ).one_or_none()
    if row is None:
        raise LookupError(f"no case {case_id}")
    if row.mentor_id != mentor_id:
        raise WrongActor("a mentor can edit drafts only on their own mentees' cases")
    if State(row.state) is not State.DRAFTED:
        raise WrongState(f"cannot edit the draft of a {row.state} case")
    clean = check_message(message)
    latest = conn.execute(
        text(
            "SELECT version, message FROM app.case_drafts WHERE case_id = :id "
            "ORDER BY version DESC LIMIT 1"
        ),
        {"id": case_id},
    ).one_or_none()
    if latest is not None and latest.message == clean:
        return int(latest.version)
    version = _add_draft(conn, case_id, "mentor", mentor_id, clean, today)
    _event(
        conn,
        case_id,
        today,
        "draft_edited",
        State.DRAFTED,
        State.DRAFTED,
        Actor.MENTOR,
        mentor_id,
        {"version": version},
    )
    return version


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


class UnknownStudent(LookupError):
    """The student id is not in `core.students`."""


@dataclass(frozen=True)
class Assignment:
    changed: bool
    cases_moved: int


def assign_mentor(
    conn: Connection, student_id: int, mentor_id: str, admin_id: str, today: date
) -> Assignment:
    """Set the student's mentor and move their open case to that mentor, in one transaction.

    A closed case keeps the mentor who handled it (it is history); a later reopen takes the
    current assignment. The audit entries carry counts and `case-<id>` references only, never
    which mentor holds which student. Setting the mentor a student already has changes nothing,
    but still moves an open case that has drifted from the assignment (an earlier CSV change
    does not move open cases). Must run as an admin: row-level security refuses others.
    """
    current = conn.execute(
        text("SELECT mentor_id FROM app.mentor_assignments WHERE student_id = :s"),
        {"s": student_id},
    ).scalar_one_or_none()
    changed = current != mentor_id
    if changed:
        try:
            with conn.begin_nested():
                conn.execute(
                    text(
                        "INSERT INTO app.mentor_assignments (student_id, mentor_id) "
                        "VALUES (:s, :m) ON CONFLICT (student_id) "
                        "DO UPDATE SET mentor_id = EXCLUDED.mentor_id"
                    ),
                    {"s": student_id, "m": mentor_id},
                )
        except IntegrityError as error:
            raise UnknownStudent(f"no student {student_id}") from error
    open_case = conn.execute(
        text(
            "SELECT id, state, mentor_id FROM app.cases "
            "WHERE student_id = :s AND state = ANY(:open) FOR UPDATE"
        ),
        {"s": student_id, "open": OPEN_VALUES},
    ).one_or_none()
    moved = 0
    if open_case is not None and open_case.mentor_id != mentor_id:
        conn.execute(
            text("UPDATE app.cases SET mentor_id = :m WHERE id = :id"),
            {"m": mentor_id, "id": open_case.id},
        )
        state = State(open_case.state)
        _event(conn, open_case.id, today, "reassigned", state, state, Actor.ADMIN, admin_id)
        moved = 1
    if changed or moved:
        audit.append(
            conn,
            actor_kind=Actor.ADMIN.value,
            actor_id=admin_id,
            action="mentor_assignment.set",
            subject_kind="student",
            subject_ref=f"student-{student_id}",
            detail={"changed": changed, "cases_moved": moved},
        )
    return Assignment(changed, moved)
