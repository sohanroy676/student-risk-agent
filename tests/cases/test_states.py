from datetime import date

import pytest

from app.cases.config import CaseConfig
from app.cases.states import (
    CLOSED_STATES,
    OPEN_STATES,
    RULES,
    Action,
    Actor,
    NotAllowed,
    State,
    WrongActor,
    WrongState,
    due_date,
    step,
)

CFG = CaseConfig()
DAY = date(2026, 3, 2)


def test_happy_path_through_one_cycle() -> None:
    s = step(State.NEW, 1, Action.SAVE_PLAN, Actor.AGENT, DAY, CFG)
    assert (s.state, s.due_on) == (State.DRAFTED, date(2026, 3, 5))
    s = step(s.state, 1, Action.APPROVE, Actor.MENTOR, DAY, CFG)
    assert (s.state, s.due_on) == (State.MONITORING, date(2026, 3, 9))
    s = step(s.state, 1, Action.FOLLOWUP_DUE, Actor.SYSTEM, date(2026, 3, 9), CFG)
    assert s.state is State.IN_REVIEW
    s = step(s.state, 1, Action.RESOLVE, Actor.MENTOR, date(2026, 3, 10), CFG)
    assert (s.state, s.closed, s.due_on) == (State.RESOLVED, True, None)


def test_continue_starts_a_second_cycle_and_a_third_escalates() -> None:
    s = step(State.IN_REVIEW, 1, Action.CONTINUE, Actor.MENTOR, DAY, CFG)
    assert (s.state, s.cycle) == (State.MONITORING, 2)
    s = step(State.IN_REVIEW, 2, Action.CONTINUE, Actor.MENTOR, DAY, CFG)
    assert (s.state, s.cycle, s.closed) == (State.ESCALATED, 2, False)


def test_every_action_from_every_wrong_state_is_refused() -> None:
    for action, (starts, actors) in RULES.items():
        for state in State:
            if state in starts:
                continue
            for actor in actors:
                with pytest.raises(NotAllowed):
                    step(state, 1, action, actor, DAY, CFG)


def test_every_action_by_every_wrong_actor_is_refused() -> None:
    for action, (starts, actors) in RULES.items():
        for actor in set(Actor) - actors:
            for state in starts:
                with pytest.raises(NotAllowed):
                    step(state, 1, action, actor, DAY, CFG)


def test_a_wrong_state_and_a_wrong_actor_are_told_apart() -> None:
    with pytest.raises(WrongState):
        step(State.NEW, 1, Action.APPROVE, Actor.MENTOR, DAY, CFG)
    with pytest.raises(WrongActor):
        step(State.DRAFTED, 1, Action.APPROVE, Actor.STAFF, DAY, CFG)


def test_when_both_are_wrong_the_actor_is_what_is_reported() -> None:
    """A caller who may not approve at all is told so, not what state the case is in."""
    with pytest.raises(WrongActor):
        step(State.NEW, 1, Action.APPROVE, Actor.STAFF, DAY, CFG)


def test_both_kinds_are_not_allowed_moves() -> None:
    assert issubclass(WrongState, NotAllowed) and issubclass(WrongActor, NotAllowed)


def test_only_a_mentor_can_approve() -> None:
    assert RULES[Action.APPROVE][1] == {Actor.MENTOR}
    for actor in (Actor.AGENT, Actor.SYSTEM, Actor.STAFF):
        with pytest.raises(NotAllowed, match="cannot approve"):
            step(State.DRAFTED, 1, Action.APPROVE, actor, DAY, CFG)


def test_only_the_agent_saves_a_plan_and_only_the_system_runs_the_timer() -> None:
    assert RULES[Action.SAVE_PLAN][1] == {Actor.AGENT}
    assert RULES[Action.FOLLOWUP_DUE][1] == {Actor.SYSTEM}


def test_closed_cases_have_no_way_out() -> None:
    for state in CLOSED_STATES:
        assert not any(state in starts for starts, _ in RULES.values())


def test_mentor_can_escalate_from_every_open_state_but_escalated() -> None:
    for state in OPEN_STATES - {State.ESCALATED}:
        assert step(state, 1, Action.ESCALATE, Actor.MENTOR, DAY, CFG).state is State.ESCALATED
    with pytest.raises(NotAllowed):
        step(State.ESCALATED, 1, Action.ESCALATE, Actor.MENTOR, DAY, CFG)


def test_escalated_cases_wait_for_staff_with_no_deadline() -> None:
    assert due_date(State.ESCALATED, DAY, CFG) is None
    assert step(State.ESCALATED, 2, Action.RESOLVE, Actor.STAFF, DAY, CFG).state is State.RESOLVED


def test_there_is_no_automatic_decision_action() -> None:
    names = {a.value for a in Action}
    assert not names & {"detain", "fine", "grade", "send", "message"}


def test_only_the_system_routes_a_new_case_to_a_person() -> None:
    assert RULES[Action.ROUTE_CRISIS] == (frozenset({State.NEW}), frozenset({Actor.SYSTEM}))
    s = step(State.NEW, 1, Action.ROUTE_CRISIS, Actor.SYSTEM, DAY, CFG)
    assert (s.state, s.closed, s.due_on) == (State.ESCALATED, False, None)
    for actor in (Actor.AGENT, Actor.MENTOR, Actor.STAFF, Actor.ADMIN):
        with pytest.raises(WrongActor):
            step(State.NEW, 1, Action.ROUTE_CRISIS, actor, DAY, CFG)
    for state in set(State) - {State.NEW}:
        with pytest.raises(WrongState):
            step(state, 1, Action.ROUTE_CRISIS, Actor.SYSTEM, DAY, CFG)
