from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.ingest.clean import clean
from app.ingest.csv_connector import read_csv_dir
from app.ingest.quality import build_report

RUN = date(2026, 2, 1)
Builder = Callable[..., dict[str, pd.DataFrame]]


def test_a_file_of_assignments_is_cleaned_into_the_app_table(good: Builder) -> None:
    raw = good(
        mentor_assignments=[
            {"student_id": 1, "mentor_id": "m1"},
            {"student_id": 2, "mentor_id": "m2"},
        ]
    )
    result = clean(raw, RUN)
    assert result.issues == []
    assert result.tables["mentor_assignments"]["mentor_id"].tolist() == ["m1", "m2"]


def test_no_assignment_file_is_not_a_problem(good: Builder) -> None:
    result = clean(good(), RUN)
    assert result.tables["mentor_assignments"].empty and result.rows_in["mentor_assignments"] == 0
    assert build_report(result, RUN).status == "ok"


def test_mentor_ids_are_trimmed_but_otherwise_kept_exactly(good: Builder) -> None:
    raw = good(
        mentor_assignments=[
            {"student_id": 1, "mentor_id": "  Dr.Rao@College  "},
            {"student_id": 2, "mentor_id": "M1"},
        ]
    )
    assert clean(raw, RUN).tables["mentor_assignments"]["mentor_id"].tolist() == [
        "Dr.Rao@College",
        "M1",
    ]


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_mentor_is_rejected_not_guessed(good: Builder, blank: str) -> None:
    raw = good(mentor_assignments=[{"student_id": 1, "mentor_id": blank}])
    result = clean(raw, RUN)
    assert result.tables["mentor_assignments"].empty
    assert result.rejected("mentor_assignments") == 1
    assert result.issues[0].code == "missing_required"


def test_an_assignment_for_an_unknown_student_is_rejected(good: Builder) -> None:
    raw = good(mentor_assignments=[{"student_id": 99, "mentor_id": "m1"}])
    result = clean(raw, RUN)
    assert result.tables["mentor_assignments"].empty
    assert [i.code for i in result.issues] == ["orphan_fk"]


def test_a_student_with_two_rows_keeps_the_later_one(good: Builder) -> None:
    raw = good(
        mentor_assignments=[
            {"student_id": 1, "mentor_id": "old"},
            {"student_id": 1, "mentor_id": "new"},
        ]
    )
    result = clean(raw, RUN)
    assert result.tables["mentor_assignments"]["mentor_id"].tolist() == ["new"]
    assert [i.code for i in result.issues] == ["duplicate_key"]


def test_a_bad_student_id_is_rejected(good: Builder) -> None:
    raw = good(mentor_assignments=[{"student_id": "one", "mentor_id": "m1"}])
    assert clean(raw, RUN).tables["mentor_assignments"].empty


def test_a_rejected_student_takes_their_assignment_with_them(good: Builder) -> None:
    raw = good(
        students=[{"id": 1, "section_id": 1}, {"id": 2, "section_id": 99}],
        mentor_assignments=[{"student_id": 2, "mentor_id": "m1"}],
    )
    result = clean(raw, RUN)
    assert result.tables["mentor_assignments"].empty


def test_text_that_looks_like_sql_is_just_a_mentor_id(good: Builder) -> None:
    hostile = "m1'); DROP TABLE app.cases;--"
    raw = good(mentor_assignments=[{"student_id": 1, "mentor_id": hostile}])
    assert clean(raw, RUN).tables["mentor_assignments"]["mentor_id"].tolist() == [hostile]


def test_the_csv_reader_picks_up_mentor_assignments_csv(tmp_path: Path) -> None:
    (tmp_path / "mentor_assignments.csv").write_text("student_id,mentor_id\n1,m1\n2,m2\n")
    frames = read_csv_dir(tmp_path)
    assert list(frames) == ["mentor_assignments"]
    assert frames["mentor_assignments"]["mentor_id"].tolist() == ["m1", "m2"]


def test_a_mostly_bad_assignment_file_fails_the_night_rather_than_half_loading(
    good: Builder,
) -> None:
    raw = good(
        mentor_assignments=[
            {"student_id": 99, "mentor_id": "m1"},
            {"student_id": 98, "mentor_id": "m1"},
            {"student_id": 1, "mentor_id": "m1"},
        ]
    )
    report = build_report(clean(raw, RUN), RUN)
    assert report.status == "fail"
    assert any("mentor_assignments" in p for p in report.problems)


def test_one_bad_row_in_a_large_assignment_file_only_warns(good: Builder) -> None:
    students = [{"id": i, "section_id": 1} for i in range(1, 41)]
    rows = [{"student_id": i, "mentor_id": "m1"} for i in range(1, 41)]
    rows.append({"student_id": 999, "mentor_id": "m1"})
    raw = good(students=students, mentor_assignments=rows)
    report = build_report(clean(raw, RUN), RUN)
    assert report.status == "warn"
