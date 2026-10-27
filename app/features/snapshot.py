"""Point-in-time feature snapshots.

`build_snapshot` uses only information that was known by the end of the `as_of` day:

- rows dated after `as_of` are ignored (attendance, LMS events, fees due);
- a mark or payment counts only if its own date is on or before `as_of`, so an
  assessment that is submitted or a fee that is paid *later* looks missing/overdue now;
- no protected attribute is ever an input.

The same function serves training (many past `as_of` dates) and nightly scoring (today),
so there is one definition of every feature. Rates are NaN when there is nothing to
average yet (a model pipeline imputes them); counts default to 0.
"""

from collections.abc import Iterable
from datetime import date

import pandas as pd

from app.features.tables import CoreTables

RECENT_ATTENDANCE_DAYS = 28
RECENT_LMS_DAYS = 14

COUNT_FEATURES = (
    "classes_held",
    "assessments_due",
    "missed_submissions",
    "late_submissions",
    "lms_events_total",
    "lms_events_14d",
    "fees_overdue_count",
    "fees_overdue_amount",
)
FEATURE_NAMES = (
    "classes_held",
    "attendance_rate",
    "attendance_rate_28d",
    "assessments_due",
    "missed_submissions",
    "late_submissions",
    "marks_pct_mean",
    "lms_events_total",
    "lms_events_14d",
    "days_since_last_lms",
    "fees_overdue_count",
    "fees_overdue_amount",
)


def _attendance(t: CoreTables, ids: pd.Index, day_end: pd.Timestamp) -> pd.DataFrame:
    att = t.attendance
    att = att[att["student_id"].isin(ids) & (att["class_date"] < day_end)]
    present = att["present"].astype(float)
    recent = att["class_date"] >= day_end - pd.Timedelta(days=RECENT_ATTENDANCE_DAYS)
    return pd.DataFrame(
        {
            "classes_held": present.groupby(att["student_id"]).size(),
            "attendance_rate": present.groupby(att["student_id"]).mean(),
            "attendance_rate_28d": present[recent].groupby(att.loc[recent, "student_id"]).mean(),
        }
    )


def _assessments(t: CoreTables, ids: pd.Index, day_end: pd.Timestamp) -> pd.DataFrame:
    due = t.assessments[t.assessments["due_date"] < day_end]
    due = due[["id", "course_id", "due_date"]].rename(columns={"id": "assessment_id"})
    enrolled = t.enrollments[t.enrollments["student_id"].isin(ids)]
    pairs = enrolled.merge(due, on="course_id")[["student_id", "assessment_id", "due_date"]]

    marks = t.marks
    submitted = marks[
        marks["student_id"].isin(ids)
        & marks["submitted_on"].notna()
        & (marks["submitted_on"] < day_end)
    ]
    joined = pairs.merge(
        submitted[["assessment_id", "student_id", "submitted_on"]],
        on=["assessment_id", "student_id"],
        how="left",
    )
    by_student = joined.groupby("student_id")

    scored = submitted[submitted["marks_obtained"].notna()].merge(
        t.assessments[["id", "max_marks"]], left_on="assessment_id", right_on="id"
    )
    pct = scored["marks_obtained"].astype(float) / scored["max_marks"].astype(float)
    return pd.DataFrame(
        {
            "assessments_due": by_student.size(),
            "missed_submissions": joined["submitted_on"].isna().groupby(joined["student_id"]).sum(),
            "late_submissions": joined["submitted_on"]
            .gt(joined["due_date"])
            .groupby(joined["student_id"])
            .sum(),
            "marks_pct_mean": pct.groupby(scored["student_id"]).mean(),
        }
    )


def _lms(t: CoreTables, ids: pd.Index, day_end: pd.Timestamp) -> pd.DataFrame:
    ev = t.lms_events
    ev = ev[ev["student_id"].isin(ids) & (ev["occurred_at"] < day_end)]
    weight = (
        ev["sum_click"].astype(float) if "sum_click" in ev.columns else pd.Series(1.0, ev.index)
    )
    recent = ev["occurred_at"] >= day_end - pd.Timedelta(days=RECENT_LMS_DAYS)
    last_day = ev["occurred_at"].groupby(ev["student_id"]).max().dt.normalize()
    return pd.DataFrame(
        {
            "lms_events_total": weight.groupby(ev["student_id"]).sum(),
            "lms_events_14d": weight[recent].groupby(ev.loc[recent, "student_id"]).sum(),
            "days_since_last_lms": (day_end - pd.Timedelta(days=1) - last_day).dt.days,
        }
    )


def _fees(t: CoreTables, ids: pd.Index, day_end: pd.Timestamp) -> pd.DataFrame:
    fees = t.fees
    fees = fees[fees["student_id"].isin(ids) & (fees["due_date"] < day_end)]
    overdue = fees[fees["paid_on"].isna() | (fees["paid_on"] >= day_end)]
    by_student = overdue.groupby("student_id")
    return pd.DataFrame(
        {
            "fees_overdue_count": by_student.size(),
            "fees_overdue_amount": overdue["amount"]
            .astype(float)
            .groupby(overdue["student_id"])
            .sum(),
        }
    )


def build_snapshot(tables: CoreTables, student_ids: Iterable[int], as_of: date) -> pd.DataFrame:
    """One row per requested student (input order, duplicates dropped), `FEATURE_NAMES` columns."""
    ids = pd.Index(list(dict.fromkeys(student_ids)), name="student_id")
    day_end = pd.Timestamp(as_of).normalize() + pd.Timedelta(days=1)
    parts = [_attendance, _assessments, _lms, _fees]
    snapshot = pd.concat([part(tables, ids, day_end) for part in parts], axis=1)
    snapshot = snapshot.reindex(index=ids, columns=list(FEATURE_NAMES)).astype(float)
    snapshot[list(COUNT_FEATURES)] = snapshot[list(COUNT_FEATURES)].fillna(0.0)
    return snapshot
