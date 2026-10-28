"""Plain-language reason text for each model feature.

Each template only states the feature's value ("Attended 62% of classes in the last four
weeks"). It never says whether the value is good or bad, so the sentence stays true whatever
the value is. Why a feature was chosen as a reason is the model's job (see `explain.py`).
Templates use no digits other than the value itself, so the shown number can be checked.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.features.snapshot import FEATURE_NAMES


@dataclass(frozen=True)
class Reason:
    """One rendered reason. `value` is the exact snapshot value the text was rendered from."""

    fact_id: str
    feature: str
    value: float
    contribution: float
    text: str


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _n(v: float) -> str:
    return f"{v:,.0f}"


def _count(v: float, singular: str, plural: str | None = None) -> str:
    """'1 submission' / '3 submissions', judged on the number as displayed."""
    shown = _n(v)
    return f"{shown} {singular if shown == '1' else plural or singular + 's'}"


def _lead(v: float) -> str:
    days = f"{abs(v):.1f}"
    if float(days) == 0:
        return "On average, work was handed in on the deadline day"
    side = "before" if v > 0 else "after"
    return f"On average, work was handed in {days} days {side} the deadline"


def _trend(v: float) -> str:
    shown = _n(abs(v))
    if shown == "0":
        return "Online activity was unchanged from the previous two weeks"
    verb = "rose" if v > 0 else "fell"
    return f"Online activity {verb} by {shown} clicks compared with the previous two weeks"


TEMPLATES: dict[str, Callable[[float], str]] = {
    "classes_held": lambda v: f"{_count(v, 'class', 'classes')} held so far",
    "attendance_rate": lambda v: f"Attended {_pct(v)} of classes so far",
    "attendance_rate_28d": lambda v: f"Attended {_pct(v)} of classes in the last four weeks",
    "assessments_due": lambda v: f"{_count(v, 'assessment')} due so far",
    "missed_submissions": lambda v: f"{_count(v, 'submission')} missed so far",
    "late_submissions": lambda v: f"{_count(v, 'submission')} handed in late",
    "marks_pct_mean": lambda v: f"Average mark so far is {_pct(v)}",
    "marks_pct_last": lambda v: f"Most recent mark was {_pct(v)}",
    "marks_pct_min": lambda v: f"Lowest mark so far is {_pct(v)}",
    "submit_lead_days_mean": _lead,
    "lms_events_total": lambda v: f"{_count(v, 'click')} on the online course so far",
    "lms_events_14d": lambda v: f"{_count(v, 'click')} on the online course in the last two weeks",
    "lms_events_prev_14d": lambda v: (
        f"{_count(v, 'click')} on the online course in the two weeks before that"
    ),
    "lms_trend": _trend,
    "lms_active_days": lambda v: f"Active on the online course on {_count(v, 'day')} so far",
    "lms_active_days_14d": lambda v: (
        f"Active on the online course on {_count(v, 'day')} in the last two weeks"
    ),
    "lms_forum_events": lambda v: f"{_count(v, 'forum interaction')} so far",
    "lms_quiz_events": lambda v: f"{_count(v, 'quiz interaction')} so far",
    "days_since_last_lms": lambda v: f"Last online activity was {_count(v, 'day')} ago",
    "fees_overdue_count": lambda v: f"{_count(v, 'fee instalment')} overdue",
    "fees_overdue_amount": lambda v: f"Overdue fees total {_n(v)}",
    "credits_enrolled": lambda v: f"Enrolled for {_count(v, 'credit')}",
    "prior_attempts": lambda v: f"{_count(v, 'previous attempt')} at this course",
}

if set(TEMPLATES) != set(FEATURE_NAMES):  # a new feature must come with its template
    raise RuntimeError(
        f"templates out of step with FEATURE_NAMES: {set(TEMPLATES) ^ set(FEATURE_NAMES)}"
    )


def render(feature: str, value: float) -> str:
    if feature not in TEMPLATES:
        raise KeyError(f"no reason template for feature {feature!r}")
    if value != value:  # NaN: there is no fact to state
        raise ValueError(f"cannot render {feature!r} without a value")
    return TEMPLATES[feature](value)
