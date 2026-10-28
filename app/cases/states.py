"""Case states, allowed moves and timers. Pure: no database, no clock.

    new --save_plan--> drafted --approve--> monitoring --followup_due--> in_review
    in_review --resolve--> resolved      in_review --continue--> monitoring (next cycle)
    any open state --escalate--> escalated --resolve--> resolved
    new | drafted | in_review --dismiss--> dismissed

A third cycle escalates instead of continuing. That routes the case to a person; it decides
nothing about the student. Only a mentor can approve, only the agent can save a plan.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from app.cases.config import CaseConfig


class State(StrEnum):
    NEW = "new"
    DRAFTED = "drafted"
    MONITORING = "monitoring"
    IN_REVIEW = "in_review"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Action(StrEnum):
    SAVE_PLAN = "save_plan"
    APPROVE = "approve"
    FOLLOWUP_DUE = "followup_due"
    RESOLVE = "resolve"
    CONTINUE = "continue"
    ESCALATE = "escalate"
    DISMISS = "dismiss"


class Actor(StrEnum):
    SYSTEM = "system"
    AGENT = "agent"
    MENTOR = "mentor"
    STAFF = "staff"  # HoD or counsellor
    ADMIN = "admin"  # moves cases between mentors; decides nothing about the student


OPEN_STATES = frozenset(
    {State.NEW, State.DRAFTED, State.MONITORING, State.IN_REVIEW, State.ESCALATED}
)
CLOSED_STATES = frozenset({State.RESOLVED, State.DISMISSED})

# action -> (states it may start from, who may do it)
RULES: dict[Action, tuple[frozenset[State], frozenset[Actor]]] = {
    Action.SAVE_PLAN: (frozenset({State.NEW}), frozenset({Actor.AGENT})),
    Action.APPROVE: (frozenset({State.DRAFTED}), frozenset({Actor.MENTOR})),
    Action.FOLLOWUP_DUE: (frozenset({State.MONITORING}), frozenset({Actor.SYSTEM})),
    Action.RESOLVE: (
        frozenset({State.IN_REVIEW, State.ESCALATED}),
        frozenset({Actor.MENTOR, Actor.STAFF}),
    ),
    Action.CONTINUE: (frozenset({State.IN_REVIEW}), frozenset({Actor.MENTOR})),
    Action.ESCALATE: (OPEN_STATES - {State.ESCALATED}, frozenset({Actor.MENTOR, Actor.STAFF})),
    Action.DISMISS: (
        frozenset({State.NEW, State.DRAFTED, State.IN_REVIEW}),
        frozenset({Actor.MENTOR, Actor.STAFF}),
    ),
}


class NotAllowed(Exception):  # noqa: N818 - reads better than NotAllowedError at call sites
    """The move is illegal from this state, or this kind of actor may not make it."""


class WrongState(NotAllowed):
    """The case is in a state this action cannot start from (HTTP 409)."""


class WrongActor(NotAllowed):
    """This kind of actor, or this person, may not make the move (HTTP 403)."""


@dataclass(frozen=True)
class Step:
    state: State
    cycle: int
    due_on: date | None
    closed: bool


def due_date(state: State, entered_on: date, cfg: CaseConfig) -> date | None:
    """When the case needs attention next; `None` for terminal and escalated cases."""
    days = {
        State.NEW: cfg.draft_due_days,
        State.DRAFTED: cfg.review_due_days,
        State.MONITORING: cfg.followup_days,
        State.IN_REVIEW: cfg.review_due_days,
    }.get(state)
    return None if days is None else entered_on + timedelta(days=days)


def step(
    state: State, cycle: int, action: Action, actor: Actor, today: date, cfg: CaseConfig
) -> Step:
    """The case after `action`, or `NotAllowed`. `continue` past `max_cycles` escalates."""
    starts, actors = RULES[action]
    if actor not in actors:
        raise WrongActor(f"a {actor.value} cannot {action.value}")
    if state not in starts:
        raise WrongState(f"cannot {action.value} a {state.value} case")
    if action is Action.SAVE_PLAN:
        new, new_cycle = State.DRAFTED, cycle
    elif action is Action.APPROVE:
        new, new_cycle = State.MONITORING, cycle
    elif action is Action.FOLLOWUP_DUE:
        new, new_cycle = State.IN_REVIEW, cycle
    elif action is Action.CONTINUE:
        new, new_cycle = (
            (State.ESCALATED, cycle) if cycle >= cfg.max_cycles else (State.MONITORING, cycle + 1)
        )
    elif action is Action.ESCALATE:
        new, new_cycle = State.ESCALATED, cycle
    elif action is Action.RESOLVE:
        new, new_cycle = State.RESOLVED, cycle
    else:
        new, new_cycle = State.DISMISSED, cycle
    return Step(new, new_cycle, due_date(new, today, cfg), new in CLOSED_STATES)
