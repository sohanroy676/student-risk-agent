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
    "lms_events_prev_14d",
    "lms_trend",
    "lms_active_days",
    "lms_active_days_14d",
    "lms_forum_events",
    "lms_quiz_events",
    "lms_content_events",
    "lms_homepage_events",
    "lms_url_events",
    "lms_collab_events",
    "lms_wiki_glossary_events",
    "lms_activity_events",
    "lms_content_events_14d",
    "lms_homepage_events_14d",
    "fees_overdue_count",
    "fees_overdue_amount",
)
# LMS event_type -> total-clicks feature; the two in RECENT_LMS_TYPES also get a 14-day count.
LMS_TYPE_FEATURES = {
    "forum_post": "lms_forum_events",
    "quiz_attempt": "lms_quiz_events",
    "content": "lms_content_events",
    "homepage": "lms_homepage_events",
    "url": "lms_url_events",
    "collab": "lms_collab_events",
    "wiki_glossary": "lms_wiki_glossary_events",
    "activity": "lms_activity_events",
}
RECENT_LMS_TYPES = ("content", "homepage")
FEATURE_NAMES = (
    "classes_held",
    "attendance_rate",
    "attendance_rate_28d",
    "assessments_due",
    "missed_submissions",
    "late_submissions",
    "marks_pct_mean",
    "marks_pct_last",
    "marks_pct_min",
    "submit_lead_days_mean",
    "lms_events_total",
    "lms_events_14d",
    "lms_events_prev_14d",
    "lms_trend",
    "lms_active_days",
    "lms_active_days_14d",
    "lms_forum_events",
    "lms_quiz_events",
    "lms_content_events",
    "lms_homepage_events",
    "lms_url_events",
    "lms_collab_events",
    "lms_wiki_glossary_events",
    "lms_activity_events",
    "lms_content_events_14d",
    "lms_homepage_events_14d",
    "days_since_last_lms",
    "fees_overdue_count",
    "fees_overdue_amount",
    "credits_enrolled",
    "prior_attempts",
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
    latest = scored.assign(pct=pct).sort_values(["submitted_on", "assessment_id"])
    lead_basis = submitted.merge(
        t.assessments[["id", "due_date"]], left_on="assessment_id", right_on="id"
    )
    lead_days = (lead_basis["due_date"] - lead_basis["submitted_on"]).dt.days
    return pd.DataFrame(
        {
            "assessments_due": by_student.size(),
            "missed_submissions": joined["submitted_on"].isna().groupby(joined["student_id"]).sum(),
            "late_submissions": joined["submitted_on"]
            .gt(joined["due_date"])
            .groupby(joined["student_id"])
            .sum(),
            "marks_pct_mean": pct.groupby(scored["student_id"]).mean(),
            "marks_pct_last": latest.groupby("student_id")["pct"].last(),
            "marks_pct_min": pct.groupby(
                scored["student_id"]
            ).min(),  # Positive = handed in before the deadline, negative = after it.
            "submit_lead_days_mean": lead_days.groupby(lead_basis["student_id"]).mean(),
        }
    )


def _lms(t: CoreTables, ids: pd.Index, day_end: pd.Timestamp) -> pd.DataFrame:
    ev = t.lms_events
    ev = ev[ev["student_id"].isin(ids) & (ev["occurred_at"] < day_end)]
    weight = (
        ev["sum_click"].astype(float) if "sum_click" in ev.columns else pd.Series(1.0, ev.index)
    )
    recent_start = day_end - pd.Timedelta(days=RECENT_LMS_DAYS)
    recent = ev["occurred_at"] >= recent_start
    previous = ~recent & (ev["occurred_at"] >= recent_start - pd.Timedelta(days=RECENT_LMS_DAYS))
    active_day = ev["occurred_at"].dt.normalize()
    last_day = ev["occurred_at"].groupby(ev["student_id"]).max().dt.normalize()

    def window_sum(mask: pd.Series) -> pd.Series:
        return weight[mask].groupby(ev.loc[mask, "student_id"]).sum()

    by_type: dict[str, pd.Series] = {}
    if "event_type" in ev.columns:
        for event_type, name in LMS_TYPE_FEATURES.items():
            is_type = ev["event_type"] == event_type
            by_type[name] = window_sum(is_type)
            if event_type in RECENT_LMS_TYPES:
                by_type[f"{name}_14d"] = window_sum(is_type & recent)
    last_14 = window_sum(recent)
    prev_14 = window_sum(previous)
    return pd.DataFrame(
        {
            "lms_events_total": weight.groupby(ev["student_id"]).sum(),
            "lms_events_14d": last_14,
            "lms_events_prev_14d": prev_14,
            "lms_trend": last_14.sub(prev_14, fill_value=0.0),
            "lms_active_days": active_day.groupby(ev["student_id"]).nunique(),
            "lms_active_days_14d": active_day[recent]
            .groupby(ev.loc[recent, "student_id"])
            .nunique(),
            **by_type,
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


def _context(t: CoreTables, ids: pd.Index, day_end: pd.Timestamp) -> pd.DataFrame:
    """Facts fixed at enrolment (credit load, earlier attempts); undated, so always known."""
    if t.student_context is None:
        return pd.DataFrame(index=pd.Index([], name="student_id"))
    context = t.student_context.drop_duplicates("student_id").set_index("student_id")
    return context.loc[context.index.isin(ids), ["credits_enrolled", "prior_attempts"]]


def build_snapshot(tables: CoreTables, student_ids: Iterable[int], as_of: date) -> pd.DataFrame:
    """One row per requested student (input order, duplicates dropped), `FEATURE_NAMES` columns."""
    ids = pd.Index(list(dict.fromkeys(student_ids)), name="student_id")
    day_end = pd.Timestamp(as_of).normalize() + pd.Timedelta(days=1)
    parts = [_attendance, _assessments, _lms, _fees, _context]
    snapshot = pd.concat([part(tables, ids, day_end) for part in parts], axis=1)
    snapshot = snapshot.reindex(index=ids, columns=list(FEATURE_NAMES)).astype(float)
    snapshot[list(COUNT_FEATURES)] = snapshot[list(COUNT_FEATURES)].fillna(0.0)
    return snapshot
