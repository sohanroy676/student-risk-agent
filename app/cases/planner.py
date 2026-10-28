"""Tonight's decisions: bands, which students get a new case, and who is deferred.

Pure: history in, plan out. Opening a case is not a decision about the student; it asks a
mentor to look. A mentor can take only `max_new_per_mentor_per_night` new cases a night, so
the highest-probability candidates go first and the rest wait (they are candidates again
tomorrow, because nothing here remembers them).
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from app.cases.bands import Band, check_probability, next_band, rising_fast
from app.cases.config import CaseConfig


class Reason(StrEnum):
    RED = "red"
    RAPID_RISE = "rapid_rise"


@dataclass(frozen=True)
class Score:
    student_id: int
    probability: float


@dataclass(frozen=True)
class History:
    """What the engine remembers about one student before tonight."""

    previous_band: Band | None = None
    probability_a_week_ago: float | None = None
    has_open_case: bool = False
    last_closed_on: date | None = None


@dataclass(frozen=True)
class NewCase:
    student_id: int
    mentor_id: str
    band: Band
    probability: float
    reason: Reason


@dataclass
class NightPlan:
    bands: dict[int, Band] = field(default_factory=dict)
    opened: list[NewCase] = field(default_factory=list)
    deferred: list[int] = field(default_factory=list)
    unassigned: list[int] = field(default_factory=list)


def _in_cooldown(history: History, p: float, as_of: date, cfg: CaseConfig) -> bool:
    if history.last_closed_on is None or p >= cfg.severe:
        return False
    return as_of < history.last_closed_on + timedelta(days=cfg.reopen_cooldown_days)


def plan_night(
    scores: Sequence[Score],
    history: Mapping[int, History],
    mentors: Mapping[int, str],
    as_of: date,
    cfg: CaseConfig,
    opened_today: Mapping[str, int] | None = None,
) -> NightPlan:
    """`opened_today` counts cases already opened for `as_of`, so a re-run cannot exceed the cap."""
    ids = [s.student_id for s in scores]
    if len(set(ids)) != len(ids):
        raise ValueError("a student appears twice in tonight's scores")
    plan = NightPlan()
    candidates: list[NewCase] = []
    for score in scores:
        p = check_probability(score.probability)
        past = history.get(score.student_id, History())
        band = next_band(past.previous_band, p, cfg)
        plan.bands[score.student_id] = band
        if past.has_open_case or _in_cooldown(past, p, as_of, cfg):
            continue
        if band is Band.RED:
            reason = Reason.RED
        elif rising_fast(p, past.probability_a_week_ago, band, cfg):
            reason = Reason.RAPID_RISE
        else:
            continue
        mentor = mentors.get(score.student_id)
        if mentor is None:
            plan.unassigned.append(score.student_id)
            continue
        candidates.append(NewCase(score.student_id, mentor, band, p, reason))
    taken: dict[str, int] = defaultdict(int, opened_today or {})
    for case in sorted(candidates, key=lambda c: (-c.probability, c.student_id)):
        if taken[case.mentor_id] >= cfg.max_new_per_mentor_per_night:
            plan.deferred.append(case.student_id)
        else:
            taken[case.mentor_id] += 1
            plan.opened.append(case)
    plan.unassigned.sort()
    return plan
