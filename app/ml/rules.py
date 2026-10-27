"""Transparent rule-based risk score: the baseline every model must beat.

Each rule maps one snapshot feature to a 0..1 concern level and carries a fixed weight;
the weights sum to 1, so the score is in [0, 1]. Returning per-rule contributions (not
just the total) keeps every score explainable. Missing data means "no evidence" (0),
except LMS: a student with no recorded activity at all counts as fully disengaged.
"""

import pandas as pd

WEIGHTS = {
    "low_attendance": 0.30,
    "missed_submissions": 0.25,
    "low_marks": 0.20,
    "lms_inactivity": 0.15,
    "overdue_fees": 0.10,
}
ATTENDANCE_OK = 0.85
ATTENDANCE_FLOOR = 0.50
MARKS_OK = 0.60
MARKS_FLOOR = 0.20
LMS_IDLE_DAYS = 14
FEES_CAP = 2


def _ramp(value: pd.Series, ok: float, floor: float) -> pd.Series:
    """0 at or above `ok`, 1 at or below `floor`, linear between; NaN stays NaN."""
    return ((ok - value) / (ok - floor)).clip(0.0, 1.0)


def rule_contributions(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Weighted concern per rule, one column per rule, same index as `snapshot`."""
    due = snapshot["assessments_due"]
    missed_share = (snapshot["missed_submissions"] / due.where(due > 0)).clip(0.0, 1.0)
    idle = (snapshot["days_since_last_lms"] / LMS_IDLE_DAYS).clip(0.0, 1.0)
    concern = pd.DataFrame(
        {
            "low_attendance": _ramp(snapshot["attendance_rate"], ATTENDANCE_OK, ATTENDANCE_FLOOR),
            "missed_submissions": missed_share,
            "low_marks": _ramp(snapshot["marks_pct_mean"], MARKS_OK, MARKS_FLOOR),
            "lms_inactivity": idle.fillna(1.0),
            "overdue_fees": (snapshot["fees_overdue_count"] / FEES_CAP).clip(0.0, 1.0),
        }
    )
    return concern.fillna(0.0) * pd.Series(WEIGHTS)


def rule_score(snapshot: pd.DataFrame) -> pd.Series:
    return rule_contributions(snapshot).sum(axis=1).rename("rule_score")
