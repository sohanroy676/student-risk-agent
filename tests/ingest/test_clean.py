from collections.abc import Callable
from datetime import date

import pandas as pd
import pytest

from app.ingest.clean import ROW, CleanResult, clean

RUN = date(2026, 2, 1)
Builder = Callable[..., dict[str, pd.DataFrame]]


def run(raw: dict[str, pd.DataFrame]) -> CleanResult:
    return clean(raw, RUN)


def test_good_data_passes_untouched(good: Builder) -> None:
    result = run(good())
    assert result.issues == []
    assert len(result.tables["marks"]) == 2
    assert result.tables["attendance"]["present"].tolist() == [True, False]
    assert result.tables["marks"]["marks_obtained"].isna().tolist() == [False, True]
    assert pd.api.types.is_datetime64_any_dtype(result.tables["attendance"]["class_date"])


def test_absent_optional_tables_come_back_empty(good: Builder) -> None:
    raw = good()
    del raw["fees"], raw["lms_events"], raw["student_attributes"]
    result = run(raw)
    assert result.tables["fees"].empty
    assert list(result.tables["fees"].columns)[0] == "id"
    assert result.rows_in["fees"] == 0


def test_missing_column_raises(good: Builder) -> None:
    raw = good()
    raw["students"] = raw["students"].drop(columns="section_id")
    with pytest.raises(ValueError, match="students is missing columns"):
        run(raw)


@pytest.mark.parametrize("value", ["abc", "12.5", "99999999999", "nan", "inf", "1,5"])
def test_bad_integers_are_rejected(good: Builder, value: str) -> None:
    result = run(good(students=[{"id": 1, "section_id": 1}, {"id": value, "section_id": 1}]))
    assert result.tables["students"]["id"].tolist() == [1]
    assert result.count("students", "bad_value") == 1


def test_empty_required_value_rejected_and_reported_with_row_number(good: Builder) -> None:
    result = run(good(students=[{"id": 1, "section_id": 1}, {"id": 2, "section_id": ""}]))
    (issue,) = [i for i in result.issues if i.table == "students"]
    assert (issue.code, issue.count, issue.rows, issue.rejected) == (
        "missing_required",
        1,
        (3,),
        True,
    )


def test_whitespace_is_stripped(good: Builder) -> None:
    result = run(good(courses=[{"id": " 1 ", "code": " CS101 ", "title": " Intro "}]))
    assert result.tables["courses"].iloc[0].tolist() == [1, "CS101", "Intro"]


def test_rejected_parent_takes_its_children_with_it(good: Builder) -> None:
    result = run(good(students=[{"id": 1, "section_id": 1}, {"id": 2, "section_id": 99}]))
    assert result.tables["students"]["id"].tolist() == [1]
    assert result.count("students", "orphan_fk") == 1
    assert result.tables["enrollments"]["student_id"].tolist() == [1]
    assert result.tables["attendance"]["student_id"].tolist() == [1]
    assert result.tables["marks"]["student_id"].tolist() == [1]


def test_duplicate_key_keeps_the_later_row(good: Builder) -> None:
    rows = [{"id": 1, "code": "OLD", "title": "a"}, {"id": 1, "code": "NEW", "title": "b"}]
    result = run(good(courses=rows))
    assert result.tables["courses"]["code"].tolist() == ["NEW"]
    assert result.count("courses", "duplicate_key") == 1


def test_invalid_later_duplicate_does_not_destroy_the_good_row(good: Builder) -> None:
    rows = [{"id": 1, "code": "KEEP", "title": "a"}, {"id": 1, "code": "", "title": "b"}]
    result = run(good(courses=rows))
    assert result.tables["courses"]["code"].tolist() == ["KEEP"]
    assert result.count("courses", "duplicate_key") == 0


def test_course_code_must_be_unique(good: Builder) -> None:
    rows = [{"id": 1, "code": "X", "title": "a"}, {"id": 2, "code": "X", "title": "b"}]
    result = run(good(courses=rows))
    assert result.tables["courses"]["id"].tolist() == [1]
    assert result.count("courses", "duplicate_unique") == 1


@pytest.mark.parametrize(
    ("table", "row"),
    [
        ("terms", {"id": 1, "name": "T", "start_date": "2026-04-19", "end_date": "2026-04-19"}),
        (
            "assessments",
            {"id": 1, "course_id": 1, "title": "Q", "due_date": "2026-01-30", "max_marks": 0},
        ),
        (
            "assessments",
            {"id": 1, "course_id": 1, "title": "Q", "due_date": "2026-01-30", "max_marks": -5},
        ),
        ("fees", {"id": 1, "student_id": 1, "due_date": "2026-01-12", "amount": 0, "paid_on": ""}),
        ("marks", {"assessment_id": 1, "student_id": 1, "marks_obtained": -1, "submitted_on": ""}),
    ],
)
def test_out_of_range_values_are_rejected(
    good: Builder, table: str, row: dict[str, object]
) -> None:
    result = run(good(**{table: [row]}))
    assert result.tables[table].empty
    assert result.count(table, "out_of_range") == 1


def test_bad_dates_are_rejected(good: Builder) -> None:
    rows = [
        {"student_id": 1, "course_id": 1, "class_date": d, "present": "1"}
        for d in ("2026-13-01", "05/01/2026", "2026-01-05", "tomorrow")
    ]
    result = run(good(attendance=rows))
    assert len(result.tables["attendance"]) == 1
    assert result.count("attendance", "bad_value") == 3


@pytest.mark.parametrize(
    ("word", "expected"),
    [("yes", True), ("P", True), ("absent", False), ("0", False), ("TRUE", True)],
)
def test_attendance_words(good: Builder, word: str, expected: bool) -> None:
    row = {"student_id": 1, "course_id": 1, "class_date": "2026-01-05", "present": word}
    assert run(good(attendance=[row])).tables["attendance"]["present"].tolist() == [expected]


def test_unknown_attendance_word_is_rejected_not_guessed(good: Builder) -> None:
    row = {"student_id": 1, "course_id": 1, "class_date": "2026-01-05", "present": "maybe"}
    assert run(good(attendance=[row])).tables["attendance"].empty


def test_marks_above_max_is_kept_with_a_warning(good: Builder) -> None:
    row = {"assessment_id": 1, "student_id": 1, "marks_obtained": 130, "submitted_on": "2026-01-30"}
    result = run(good(marks=[row]))
    assert len(result.tables["marks"]) == 1
    (issue,) = result.issues
    assert (issue.code, issue.rejected) == ("marks_above_max", False)


def test_mark_without_date_and_future_date_warn(good: Builder) -> None:
    marks = [
        {"assessment_id": 1, "student_id": 1, "marks_obtained": 50, "submitted_on": ""},
        {"assessment_id": 1, "student_id": 2, "marks_obtained": 50, "submitted_on": "2026-06-01"},
    ]
    result = run(good(marks=marks))
    assert len(result.tables["marks"]) == 2
    assert {i.code for i in result.issues} == {"mark_without_date", "future_date"}
    assert not any(i.rejected for i in result.issues)


def test_text_that_looks_like_sql_or_a_formula_is_just_data(good: Builder) -> None:
    title = "x'); DROP TABLE core.students;--"
    result = run(good(courses=[{"id": 1, "code": "=1+1", "title": title}]))
    assert result.tables["courses"]["title"].tolist() == [title]


def test_issues_name_source_rows_only(good: Builder) -> None:
    result = run(good(students=[{"id": "zz", "section_id": 1}]))
    assert all(isinstance(r, int) for i in result.issues for r in i.rows)
    assert ROW not in result.tables["students"].columns


def test_cleaning_twice_changes_nothing(good: Builder) -> None:
    first = run(good())
    again = {}
    for name, frame in first.tables.items():
        text = frame.astype(str).fillna("")
        text[ROW] = range(2, len(text) + 2)
        again[name] = text
    second = run(again)
    assert second.issues == []
    for name, frame in first.tables.items():
        pd.testing.assert_frame_equal(frame, second.tables[name], check_dtype=False)
