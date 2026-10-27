from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pandas.testing import assert_frame_equal

from app.features.snapshot import FEATURE_NAMES, build_snapshot
from app.features.tables import CoreTables
from data.synthetic import generator
from data.synthetic.frames import to_core_tables, to_frames

BASE = date(2026, 1, 1)
PROTECTED_NAMES = {"gender", "category", "region", "nationality", "disability", "age_band"}


def day(offset: int) -> date:
    return BASE + timedelta(days=offset)


def _frame(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    # Keep extra columns (e.g. sum_click) when rows are given.
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns)


def tables_from(rows: dict[str, list[dict[str, Any]]]) -> CoreTables:
    columns = {
        "enrollments": ["student_id", "course_id"],
        "attendance": ["student_id", "course_id", "class_date", "present"],
        "assessments": ["id", "course_id", "due_date", "max_marks"],
        "marks": ["assessment_id", "student_id", "marks_obtained", "submitted_on"],
        "fees": ["student_id", "due_date", "amount", "paid_on"],
        "lms_events": ["student_id", "course_id", "occurred_at"],
    }
    return CoreTables.from_frames(
        **{name: _frame(rows.get(name, []), cols) for name, cols in columns.items()}
    )


# ---------- Hypothesis leakage test ----------


@st.composite
def worlds(draw: st.DrawFn) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], date]:
    """A base world knowable at as_of, plus the facts that only arrive after it."""
    as_of_offset = draw(st.integers(0, 60))
    students = list(range(1, draw(st.integers(1, 4)) + 1))
    courses = list(range(1, draw(st.integers(1, 2)) + 1))
    past = st.integers(0, as_of_offset)
    future = st.integers(as_of_offset + 1, as_of_offset + 60)

    rows: dict[str, list[dict[str, Any]]] = {
        "enrollments": [{"student_id": s, "course_id": c} for s in students for c in courses]
    }
    rows["attendance"] = [
        {
            "student_id": draw(st.sampled_from(students)),
            "course_id": draw(st.sampled_from(courses)),
            "class_date": day(draw(past)),
            "present": draw(st.booleans()),
        }
        for _ in range(draw(st.integers(0, 12)))
    ]
    rows["assessments"] = [
        {"id": i, "course_id": draw(st.sampled_from(courses)), "due_date": day(draw(past)),
         "max_marks": 100}
        for i in range(1, draw(st.integers(0, 3)) + 1)
    ]  # fmt: skip
    base_pairs = set()
    rows["marks"] = []
    for a in rows["assessments"]:
        for s in students:
            if draw(st.booleans()):
                base_pairs.add((a["id"], s))
                rows["marks"].append(
                    {
                        "assessment_id": a["id"],
                        "student_id": s,
                        "marks_obtained": draw(st.integers(0, 100)),
                        "submitted_on": day(draw(past)),
                    }
                )
    rows["fees"] = [
        {
            "student_id": s,
            "due_date": day(draw(past)),
            "amount": draw(st.integers(1, 1000)),
            "paid_on": day(draw(past)) if draw(st.booleans()) else None,
        }
        for s in students
        for _ in range(draw(st.integers(0, 2)))
    ]
    rows["lms_events"] = [
        {
            "student_id": draw(st.sampled_from(students)),
            "course_id": draw(st.sampled_from(courses)),
            "occurred_at": datetime.combine(day(draw(past)), datetime.min.time())
            + timedelta(hours=draw(st.integers(0, 23))),
        }
        for _ in range(draw(st.integers(0, 12)))
    ]

    later: dict[str, Any] = {
        "attendance": [
            {
                "student_id": draw(st.sampled_from(students)),
                "course_id": draw(st.sampled_from(courses)),
                "class_date": day(draw(future)),
                "present": draw(st.booleans()),
            }
            for _ in range(draw(st.integers(0, 6)))
        ],
        "lms_events": [
            {
                "student_id": draw(st.sampled_from(students)),
                "course_id": draw(st.sampled_from(courses)),
                "occurred_at": datetime.combine(day(draw(future)), datetime.min.time()),
            }
            for _ in range(draw(st.integers(0, 6)))
        ],
        # Late submissions for pairs that had no mark at as_of.
        "late_marks": [
            {
                "assessment_id": a["id"],
                "student_id": s,
                "marks_obtained": draw(st.integers(0, 100)),
                "submitted_on": day(draw(future)),
            }
            for a in rows["assessments"]
            for s in students
            if (a["id"], s) not in base_pairs and draw(st.booleans())
        ],
        # Assessments and fees that only fall due after as_of, with whatever follows them.
        "new_assessment": {
            "id": 99,
            "course_id": courses[0],
            "due_date": day(draw(future)),
            "max_marks": 100,
        },  # fmt: skip
        "new_fee": {
            "student_id": students[0],
            "due_date": day(draw(future)),
            "amount": 500,
            "paid_on": None,
        },  # fmt: skip
        "pay_later": draw(future),
    }
    return rows, later, day(as_of_offset)


@settings(max_examples=150, deadline=None)
@given(worlds())
def test_rows_dated_after_as_of_never_change_the_snapshot(
    world: tuple[dict[str, list[dict[str, Any]]], dict[str, Any], date],
) -> None:
    rows, later, as_of = world
    ids = sorted({r["student_id"] for r in rows["enrollments"]})
    before = build_snapshot(tables_from(rows), ids, as_of)

    after_rows = {name: [dict(r) for r in value] for name, value in rows.items()}
    after_rows["attendance"] += later["attendance"]
    after_rows["lms_events"] += later["lms_events"]
    after_rows["marks"] += later["late_marks"]
    after_rows["assessments"].append(later["new_assessment"])
    after_rows["marks"].append(
        {
            "assessment_id": 99,
            "student_id": ids[0],
            "marks_obtained": 100,
            "submitted_on": later["new_assessment"]["due_date"],
        }  # fmt: skip
    )
    after_rows["fees"].append(later["new_fee"])
    for fee in after_rows["fees"]:  # a fee unpaid at as_of is paid later: still overdue now
        if fee["paid_on"] is None:
            fee["paid_on"] = day(later["pay_later"])
    after = build_snapshot(tables_from(after_rows), ids, as_of)

    assert_frame_equal(before, after)


# ---------- Synthetic college ----------


@pytest.fixture(scope="module")
def synthetic() -> generator.SyntheticData:
    return generator.generate(seed=7)


def test_full_term_data_equals_data_truncated_to_as_of(synthetic: generator.SyntheticData) -> None:
    as_of = generator.TERM_START + timedelta(weeks=7, days=3)
    cutoff = pd.Timestamp(as_of) + pd.Timedelta(days=1)
    ids = list(range(1, generator.N_STUDENTS + 1))
    full = to_frames(synthetic)

    # Oracle: physically remove everything not yet known, written independently of the builder.
    cut = {name: frame.copy() for name, frame in full.items()}
    cut["attendance"] = cut["attendance"][pd.to_datetime(cut["attendance"]["class_date"]) < cutoff]
    cut["lms_events"] = cut["lms_events"][pd.to_datetime(cut["lms_events"]["occurred_at"]) < cutoff]
    cut["fees"] = cut["fees"][pd.to_datetime(cut["fees"]["due_date"]) < cutoff]
    paid = pd.to_datetime(cut["fees"]["paid_on"])
    cut["fees"]["paid_on"] = paid.where(paid < cutoff, pd.NaT)
    cut["assessments"] = cut["assessments"][pd.to_datetime(cut["assessments"]["due_date"]) < cutoff]
    submitted = pd.to_datetime(cut["marks"]["submitted_on"])
    cut["marks"] = cut["marks"][submitted.notna() & (submitted < cutoff)]

    assert_frame_equal(
        build_snapshot(to_core_tables(synthetic), ids, as_of),
        build_snapshot(CoreTables.from_frames(**cut), ids, as_of),
    )


def test_planted_struggling_students_look_worse(synthetic: generator.SyntheticData) -> None:
    as_of = generator.TERM_START + timedelta(weeks=9)
    ids = list(range(1, generator.N_STUDENTS + 1))
    snap = build_snapshot(to_core_tables(synthetic), ids, as_of)
    flag = snap.index.isin(list(synthetic.struggling_ids))
    assert (
        snap.loc[flag, "attendance_rate"].mean() < snap.loc[~flag, "attendance_rate"].mean() - 0.2
    )
    assert (
        snap.loc[flag, "missed_submissions"].mean() > snap.loc[~flag, "missed_submissions"].mean()
    )
    assert snap.loc[flag, "lms_events_14d"].mean() < snap.loc[~flag, "lms_events_14d"].mean()


def test_snapshot_is_deterministic(synthetic: generator.SyntheticData) -> None:
    tables = to_core_tables(synthetic)
    as_of = generator.TERM_START + timedelta(weeks=4)
    ids = [5, 1, 3]
    assert_frame_equal(build_snapshot(tables, ids, as_of), build_snapshot(tables, ids, as_of))


# ---------- Hand-computed behaviour ----------

AS_OF = date(2026, 3, 10)


def _att(d: date, present: bool) -> dict[str, Any]:
    return {"student_id": 1, "course_id": 1, "class_date": d, "present": present}


def _mark(assessment_id: int, score: int, submitted: date) -> dict[str, Any]:
    return {
        "assessment_id": assessment_id,
        "student_id": 1,
        "marks_obtained": score,
        "submitted_on": submitted,
    }


def _fee(due: date, amount: int, paid: date | None) -> dict[str, Any]:
    return {"student_id": 1, "due_date": due, "amount": amount, "paid_on": paid}


def _lms(at: datetime) -> dict[str, Any]:
    return {"student_id": 1, "course_id": 1, "occurred_at": at}


def small_world() -> CoreTables:
    return tables_from(
        {
            "enrollments": [{"student_id": 1, "course_id": 1}],
            "attendance": [
                _att(date(2026, 3, 9), True),
                _att(date(2026, 3, 10), False),
                _att(date(2026, 1, 5), False),
                _att(date(2026, 3, 11), True),
            ],
            "assessments": [
                {"id": 1, "course_id": 1, "due_date": date(2026, 3, 1), "max_marks": 50},
                {"id": 2, "course_id": 1, "due_date": date(2026, 3, 5), "max_marks": 100},
                {"id": 3, "course_id": 1, "due_date": date(2026, 3, 20), "max_marks": 100},
            ],
            "marks": [_mark(1, 25, date(2026, 3, 1)), _mark(2, 90, date(2026, 3, 12))],
            "fees": [
                _fee(date(2026, 3, 1), 100, date(2026, 3, 11)),
                _fee(date(2026, 3, 8), 50, None),
                _fee(date(2026, 3, 11), 70, None),
            ],
            "lms_events": [
                _lms(datetime(2026, 3, 10, 23, 59)),
                _lms(datetime(2026, 3, 8, 9, 0)),
                _lms(datetime(2026, 3, 11, 0, 0)),
            ],
        }
    )


def test_hand_computed_values() -> None:
    row = build_snapshot(small_world(), [1], AS_OF).iloc[0]
    assert row["classes_held"] == 3  # the 11th is after as_of
    assert row["attendance_rate"] == pytest.approx(1 / 3)
    assert row["attendance_rate_28d"] == pytest.approx(0.5)  # Jan 5 is outside 28 days
    assert row["assessments_due"] == 2  # assessment 3 is not due yet
    assert row["missed_submissions"] == 1  # assessment 2 was only submitted on the 12th
    assert row["late_submissions"] == 0
    assert row["marks_pct_mean"] == pytest.approx(0.5)  # only assessment 1 was submitted by as_of
    assert row["lms_events_total"] == 2  # as_of's last minute counts, midnight after does not
    assert row["lms_events_14d"] == 2
    assert row["days_since_last_lms"] == 0
    assert row["fees_overdue_count"] == 2  # paid on the 11th looks overdue on the 10th
    assert row["fees_overdue_amount"] == 150  # fee due on the 11th is not due yet


def test_as_of_boundary_is_inclusive_of_the_whole_day() -> None:
    tables = small_world()
    assert build_snapshot(tables, [1], date(2026, 3, 9)).iloc[0]["lms_events_total"] == 1
    assert build_snapshot(tables, [1], date(2026, 3, 11)).iloc[0]["lms_events_total"] == 3


def test_late_submission_is_counted_once_known() -> None:
    row = build_snapshot(small_world(), [1], date(2026, 3, 12)).iloc[0]
    assert row["missed_submissions"] == 0
    assert row["late_submissions"] == 1
    assert row["marks_pct_mean"] == pytest.approx((0.5 + 0.9) / 2)


def test_mark_without_submission_date_is_unknown() -> None:
    rows: dict[str, list[dict[str, Any]]] = {
        "enrollments": [{"student_id": 1, "course_id": 1}],
        "assessments": [{"id": 1, "course_id": 1, "due_date": date(2026, 3, 1), "max_marks": 100}],
        "marks": [
            {"assessment_id": 1, "student_id": 1, "marks_obtained": 80, "submitted_on": None}
        ],
    }
    row = build_snapshot(tables_from(rows), [1], AS_OF).iloc[0]
    assert row["missed_submissions"] == 1
    assert pd.isna(row["marks_pct_mean"])


def test_sum_click_weights_lms_events_when_present() -> None:
    rows = {
        "enrollments": [{"student_id": 1, "course_id": 1}],
        "lms_events": [
            {"student_id": 1, "course_id": 1, "occurred_at": datetime(2026, 3, 9), "sum_click": 5},
            {"student_id": 1, "course_id": 1, "occurred_at": datetime(2026, 3, 10), "sum_click": 2},
        ],
    }
    row = build_snapshot(tables_from(rows), [1], AS_OF).iloc[0]
    assert row["lms_events_total"] == 7


# ---------- Shape, inputs, protected attributes ----------


def test_columns_index_and_duplicates() -> None:
    snap = build_snapshot(small_world(), [1, 1], AS_OF)
    assert list(snap.columns) == list(FEATURE_NAMES)
    assert snap.index.tolist() == [1]
    assert snap.index.name == "student_id"


def test_unknown_student_gets_zero_counts_and_nan_rates() -> None:
    snap = build_snapshot(small_world(), [1, 999], AS_OF)
    assert snap.index.tolist() == [1, 999]
    row = snap.loc[999]
    assert row["classes_held"] == 0
    assert row["fees_overdue_amount"] == 0
    assert pd.isna(row["attendance_rate"])
    assert pd.isna(row["days_since_last_lms"])


def test_empty_student_list_returns_empty_frame_with_columns() -> None:
    snap = build_snapshot(small_world(), [], AS_OF)
    assert snap.empty
    assert list(snap.columns) == list(FEATURE_NAMES)


def test_as_of_before_everything_is_all_zero_or_nan() -> None:
    row = build_snapshot(small_world(), [1], date(2000, 1, 1)).iloc[0]
    assert row["classes_held"] == 0
    assert pd.isna(row["attendance_rate"])


def test_requested_students_do_not_affect_each_others_features(
    synthetic: generator.SyntheticData,
) -> None:
    tables = to_core_tables(synthetic)
    as_of = generator.TERM_START + timedelta(weeks=6)
    together = build_snapshot(tables, [1, 2, 3, 4], as_of)
    alone = build_snapshot(tables, [3], as_of)
    assert_frame_equal(together.loc[[3]], alone)


def test_no_protected_attribute_can_reach_a_feature() -> None:
    assert not PROTECTED_NAMES & set(FEATURE_NAMES)
    assert "student_attributes" not in CoreTables.__dataclass_fields__
    assert not any("attribute" in f for f in CoreTables.__dataclass_fields__)


def test_from_frames_rejects_missing_table_and_column() -> None:
    good = {
        n: pd.DataFrame() for n in ("enrollments", "attendance", "assessments", "marks", "fees")
    }
    with pytest.raises(ValueError, match="Missing tables"):
        CoreTables.from_frames(**good)
    frames = to_frames(generator.generate(seed=1))
    frames["fees"] = frames["fees"].drop(columns=["paid_on"])
    with pytest.raises(ValueError, match="paid_on"):
        CoreTables.from_frames(**frames)
