import pandas as pd
import pytest

from app.features.snapshot import FEATURE_NAMES
from app.ml.rules import WEIGHTS, rule_contributions, rule_score

GOOD = {
    "attendance_rate": 0.95,
    "assessments_due": 4,
    "missed_submissions": 0,
    "marks_pct_mean": 0.8,
    "days_since_last_lms": 0,
    "fees_overdue_count": 0,
}
WORST = {
    "attendance_rate": 0.2,
    "assessments_due": 4,
    "missed_submissions": 4,
    "marks_pct_mean": 0.1,
    "days_since_last_lms": 30,
    "fees_overdue_count": 3,
}


def snapshot(*rows: dict[str, float]) -> pd.DataFrame:
    frame = pd.DataFrame(
        index=pd.Index(range(len(rows)), name="student_id"), columns=list(FEATURE_NAMES)
    ).astype(float)
    for i, row in enumerate(rows):
        for name, value in row.items():
            frame.loc[i, name] = value
    return frame


def test_weights_sum_to_one() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_best_and_worst_student_hit_the_bounds() -> None:
    score = rule_score(snapshot(GOOD, WORST))
    assert score.iloc[0] == pytest.approx(0.0)
    assert score.iloc[1] == pytest.approx(1.0)


def test_contributions_add_up_to_the_score_and_name_every_rule() -> None:
    snap = snapshot(GOOD, WORST, {"attendance_rate": 0.6})
    parts = rule_contributions(snap)
    assert set(parts.columns) == set(WEIGHTS)
    pd.testing.assert_series_equal(parts.sum(axis=1).rename("rule_score"), rule_score(snap))
    assert (parts.le(pd.Series(WEIGHTS)) & parts.ge(0)).all().all()


def test_worse_attendance_never_lowers_the_score() -> None:
    rates = [1.0, 0.9, 0.85, 0.7, 0.5, 0.3, 0.0]
    scores = rule_score(snapshot(*({**GOOD, "attendance_rate": r} for r in rates)))
    assert scores.is_monotonic_increasing


def test_no_data_means_no_evidence_except_lms_silence() -> None:
    row = rule_contributions(snapshot({})).iloc[0]
    assert row["lms_inactivity"] == pytest.approx(WEIGHTS["lms_inactivity"])
    assert row.drop("lms_inactivity").sum() == 0


def test_zero_assessments_due_does_not_divide_by_zero() -> None:
    score = rule_score(snapshot({**GOOD, "assessments_due": 0, "missed_submissions": 0}))
    assert score.iloc[0] == pytest.approx(0.0)


def test_extreme_values_are_clipped() -> None:
    extreme = {
        **WORST,
        "days_since_last_lms": 10_000,
        "fees_overdue_count": 99,
        "attendance_rate": -1.0,
        "missed_submissions": 40,
    }
    assert rule_score(snapshot(extreme)).iloc[0] == pytest.approx(1.0)


def test_empty_snapshot_gives_empty_score() -> None:
    assert rule_score(snapshot()).empty
