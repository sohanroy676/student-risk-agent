import json
from collections.abc import Callable
from datetime import date

import pandas as pd

from app.ingest.clean import clean
from app.ingest.quality import DataQualityReport, build_report

Builder = Callable[..., dict[str, pd.DataFrame]]


def report_for(
    raw: dict[str, pd.DataFrame], run_date: date = date(2026, 2, 1)
) -> DataQualityReport:
    return build_report(clean(raw, run_date), run_date)


def test_clean_fresh_data_is_ok(good: Builder) -> None:
    report = report_for(good())
    assert report.status == "ok"
    assert report.problems == []
    assert {t.table: t.rows_loaded for t in report.tables}["marks"] == 2


def test_a_warning_makes_it_warn(good: Builder) -> None:
    marks = [
        {"assessment_id": 1, "student_id": 1, "marks_obtained": 130, "submitted_on": "2026-01-30"}
    ]
    report = report_for(good(marks=marks))
    assert report.status == "warn"
    assert report.problems == []


def test_stale_data_warns(good: Builder) -> None:
    report = report_for(good(), run_date=date(2026, 3, 1))
    assert report.status == "warn"
    assert any("older than" in p for p in report.problems)


def test_empty_essential_table_fails(good: Builder) -> None:
    raw = good()
    del raw["attendance"]
    report = report_for(raw)
    assert report.status == "fail"
    assert "attendance: no usable rows" in report.problems


def test_too_many_rejects_fail(good: Builder) -> None:
    students = [
        {"id": 1, "section_id": 1},
        {"id": 2, "section_id": 1},
        {"id": "x", "section_id": 1},
    ]
    report = report_for(good(students=students))
    assert report.status == "fail"
    assert any(p.startswith("students: 1 of 3") for p in report.problems)


def test_few_rejects_stay_a_warning(good: Builder) -> None:
    rows = [
        {"student_id": 1, "course_id": 1, "class_date": f"2026-01-{d:02d}", "present": "1"}
        for d in range(1, 29)
    ]
    rows.append({"student_id": 1, "course_id": 1, "class_date": "bad", "present": "1"})
    report = report_for(good(attendance=rows))
    assert report.status == "warn"
    assert {t.table: t.rejected for t in report.tables}["attendance"] == 1


def test_coverage_counts(good: Builder) -> None:
    students = [{"id": i, "section_id": 1} for i in (1, 2, 3)]
    report = report_for(good(students=students))
    assert report.students_without_enrollment == 1
    attendance = [{"student_id": 1, "course_id": 1, "class_date": "2026-01-05", "present": "1"}]
    assert report_for(good(attendance=attendance)).enrolled_without_attendance == 1


def test_report_holds_no_student_values(good: Builder) -> None:
    marker = "ZZ-SECRET-NAME"
    courses = [
        {"id": 1, "code": marker, "title": marker},
        {"id": "bad", "code": marker, "title": marker},
    ]
    report = report_for(good(courses=courses))
    assert marker not in report.to_json()
    assert marker not in report.render()


def test_report_round_trips_through_json_and_renders(good: Builder) -> None:
    report = report_for(good(), run_date=date(2026, 3, 1))
    data = json.loads(report.to_json())
    assert data["status"] == "warn" and data["run_date"] == "2026-03-01"
    text = report.render()
    assert text.startswith("Data quality 2026-03-01: WARN")
    assert "marks:" in text
