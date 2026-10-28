from collections import Counter
from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.cases.bands import Band
from app.cases.config import CaseConfig
from app.cases.planner import History, Reason, Score, plan_night

CFG = CaseConfig()
DAY = date(2026, 3, 2)


def plan(
    scores: dict[int, float],
    mentors: dict[int, str] | None = None,
    history: dict[int, History] | None = None,
    opened_today: dict[str, int] | None = None,
    cfg: CaseConfig = CFG,
):  # noqa: ANN201 - test helper
    mentors = mentors if mentors is not None else dict.fromkeys(scores, "m1")
    return plan_night(
        [Score(i, p) for i, p in scores.items()], history or {}, mentors, DAY, cfg, opened_today
    )


def test_red_opens_a_case_and_amber_or_green_do_not() -> None:
    result = plan({1: 0.80, 2: 0.40, 3: 0.05})
    assert [(c.student_id, c.reason, c.band) for c in result.opened] == [(1, Reason.RED, Band.RED)]
    assert result.bands == {1: Band.RED, 2: Band.AMBER, 3: Band.GREEN}


def test_a_fast_riser_opens_before_turning_red() -> None:
    history = {1: History(previous_band=Band.GREEN, probability_a_week_ago=0.20)}
    (case,) = plan({1: 0.36}, history=history).opened
    assert (case.reason, case.band) == (Reason.RAPID_RISE, Band.AMBER)
    assert plan({1: 0.34}, history=history).opened == []  # +0.14 is not enough


def test_a_student_with_an_open_case_gets_no_second_one() -> None:
    result = plan({1: 0.9}, history={1: History(has_open_case=True)})
    assert result.opened == [] and result.deferred == []
    assert result.bands[1] is Band.RED  # the band is still recorded


@pytest.mark.parametrize(
    ("days_since_close", "p", "opens"),
    [(27, 0.60, False), (28, 0.60, True), (1, 0.69, False), (1, 0.70, True)],
)
def test_reopen_cooldown_and_the_severe_exception(
    days_since_close: int, p: float, opens: bool
) -> None:
    history = {1: History(last_closed_on=DAY - timedelta(days=days_since_close))}
    assert bool(plan({1: p}, history=history).opened) is opens


def test_rate_limit_keeps_the_highest_scores_and_defers_the_rest() -> None:
    scores = {1: 0.60, 2: 0.95, 3: 0.70, 4: 0.55, 5: 0.80}
    result = plan(scores)
    assert [c.student_id for c in result.opened] == [2, 5, 3]
    assert result.deferred == [1, 4]


def test_rate_limit_is_per_mentor() -> None:
    scores = {i: 0.9 - i / 100 for i in range(1, 9)}
    mentors = {i: "a" if i <= 5 else "b" for i in scores}
    result = plan(scores, mentors)
    assert Counter(c.mentor_id for c in result.opened) == {"a": 3, "b": 3}
    assert result.deferred == [4, 5]


def test_cases_already_opened_tonight_count_against_the_cap() -> None:
    result = plan({1: 0.9, 2: 0.8}, opened_today={"m1": 2})
    assert [c.student_id for c in result.opened] == [1]
    assert result.deferred == [2]
    assert plan({1: 0.9}, opened_today={"m1": 3}).opened == []


def test_ties_break_by_student_id() -> None:
    result = plan({7: 0.9, 3: 0.9, 5: 0.9, 1: 0.9})
    assert [c.student_id for c in result.opened] == [1, 3, 5]


def test_unassigned_students_are_reported_and_use_no_capacity() -> None:
    scores = {1: 0.9, 2: 0.9, 3: 0.9, 4: 0.9}
    result = plan(scores, mentors={2: "m1", 3: "m1", 4: "m1"})
    assert result.unassigned == [1]
    assert [c.student_id for c in result.opened] == [2, 3, 4]


def test_empty_night_is_fine() -> None:
    result = plan({})
    assert result.opened == result.deferred == result.unassigned == []


def test_duplicate_student_is_an_error() -> None:
    with pytest.raises(ValueError, match="twice"):
        plan_night([Score(1, 0.5), Score(1, 0.6)], {}, {1: "m"}, DAY, CFG)


@pytest.mark.parametrize("bad", [float("nan"), 1.5, -0.2])
def test_a_bad_score_stops_the_whole_night(bad: float) -> None:
    with pytest.raises(ValueError, match="probability"):
        plan({1: 0.9, 2: bad})


def test_hysteresis_uses_yesterdays_band() -> None:
    history = {1: History(previous_band=Band.RED)}
    result = plan({1: 0.47}, history=history)
    assert result.bands[1] is Band.RED and [c.student_id for c in result.opened] == [1]
    assert plan({1: 0.47}).bands[1] is Band.AMBER


students = st.integers(min_value=1, max_value=40)


@given(
    scores=st.dictionaries(students, st.floats(min_value=0, max_value=1), max_size=40),
    mentor_of=st.dictionaries(students, st.sampled_from(["a", "b", "c"]), max_size=40),
    open_ids=st.sets(students, max_size=10),
    cap=st.integers(min_value=1, max_value=4),
    seed=st.randoms(use_true_random=False),
)
def test_plan_properties(
    scores: dict[int, float],
    mentor_of: dict[int, str],
    open_ids: set[int],
    cap: int,
    seed: object,
) -> None:
    cfg = CaseConfig(max_new_per_mentor_per_night=cap)
    history = {i: History(has_open_case=True) for i in open_ids}
    result = plan(scores, mentor_of, history, cfg=cfg)
    per_mentor = Counter(c.mentor_id for c in result.opened)
    assert all(n <= cap for n in per_mentor.values())
    opened = {c.student_id for c in result.opened}
    assert not opened & open_ids
    assert opened.isdisjoint(result.deferred) and opened.isdisjoint(result.unassigned)
    assert set(result.deferred).isdisjoint(result.unassigned)
    # Everything deferred was blocked only by a full mentor, and scored no higher than the cut.
    for sid in result.deferred:
        mentor = mentor_of[sid]
        assert per_mentor[mentor] == cap
        assert all(c.probability >= scores[sid] for c in result.opened if c.mentor_id == mentor)
    # Input order must not matter.
    shuffled = dict(scores)
    items = list(shuffled.items())
    seed.shuffle(items)  # type: ignore[attr-defined]
    again = plan(dict(items), mentor_of, history, cfg=cfg)
    assert again == result
