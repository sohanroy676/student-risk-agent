from pathlib import Path

import pandas as pd
import pytest

from app.ingest.oulad import load_oulad, presentation_start

INFO = """code_module,code_presentation,id_student,gender,region,highest_education,imd_band,\
age_band,num_of_prev_attempts,studied_credits,disability,final_result
AAA,2013J,1,M,Wales,A Level,10-20%,0-35,0,60,N,Pass
AAA,2013J,2,F,Wales,A Level,10-20%,0-35,0,60,N,Withdrawn
AAA,2014J,1,M,Wales,A Level,10-20%,0-35,1,60,N,Fail
BBB,2013J,3,F,Kent,HE,?,35-55,0,60,Y,Distinction
AAA,2013J,1,M,Wales,A Level,10-20%,0-35,0,60,N,Pass
"""
COURSES = """code_module,code_presentation,module_presentation_length
AAA,2013J,268
AAA,2014J,269
BBB,2013J,240
"""
ASSESSMENTS = """code_module,code_presentation,id_assessment,assessment_type,date,weight
AAA,2013J,10,TMA,19,10
AAA,2013J,11,Exam,,100
AAA,2014J,12,TMA,19,10
"""
STUDENT_ASSESSMENT = """id_assessment,id_student,date_submitted,is_banked,score
10,1,18,0,80
10,2,25,0,
11,1,260,0,70
10,1,18,1,99
12,1,20,0,50
"""
VLE = """code_module,code_presentation,id_student,id_site,date,sum_click
AAA,2013J,1,500,-5,3
AAA,2013J,1,501,0,2
AAA,2014J,1,500,7,4
BBB,2013J,3,502,1,1
"""


@pytest.fixture
def oulad_dir(tmp_path: Path) -> Path:
    files = {
        "studentInfo.csv": INFO,
        "courses.csv": COURSES,
        "assessments.csv": ASSESSMENTS,
        "studentAssessment.csv": STUDENT_ASSESSMENT,
        "studentVle.csv": VLE,
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_presentation_start_maps_codes_to_dates() -> None:
    assert presentation_start("2013J") == pd.Timestamp("2013-10-01")
    assert presentation_start("2014B") == pd.Timestamp("2014-02-01")


@pytest.mark.parametrize("code", ["", "2013", "2013X", "J", "abcdJ"])
def test_presentation_start_rejects_unknown_codes(code: str) -> None:
    with pytest.raises(ValueError, match="presentation code"):
        presentation_start(code)


def test_same_person_in_two_presentations_gets_two_students(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    # (AAA,2013J,1), (AAA,2013J,2), (AAA,2014J,1), (BBB,2013J,3); the duplicate row is dropped.
    assert len(data.students) == 4
    assert data.students["id"].is_unique


def test_labels_flag_withdrawn_and_fail_only(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    by_result = data.labels.set_index("student_id")["at_risk"]
    assert by_result.sum() == 2
    assert len(by_result) == 4


def test_dates_are_offsets_from_presentation_start(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    first = data.lms_events.sort_values("occurred_at").iloc[0]
    assert first["occurred_at"] == pd.Timestamp("2013-10-01") - pd.Timedelta(days=5)
    assert len(data.lms_events) == 4


def test_exam_without_date_falls_back_to_presentation_end(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    exam = data.assessments.set_index("id").loc[11]
    assert exam["due_date"] == pd.Timestamp("2013-10-01") + pd.Timedelta(days=268)
    assert data.assessments.set_index("id").loc[10, "due_date"] == pd.Timestamp("2013-10-20")


def test_banked_results_are_excluded_and_missing_scores_kept(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    assert len(data.marks) == 4  # 5 raw rows minus the banked one
    assert (data.marks["marks_obtained"] == 99).sum() == 0
    assert data.marks["marks_obtained"].isna().sum() == 1


def test_protected_attributes_stay_out_of_core_tables(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    protected = {"gender", "region", "highest_education", "imd_band", "age_band", "disability"}
    for frame in (
        data.students,
        data.enrollments,
        data.marks,
        data.lms_events,
        data.assessments,
        data.labels,
    ):
        assert not protected & set(frame.columns)
    assert protected <= set(data.attributes.columns)


def test_foreign_keys_resolve(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    assert set(data.marks["student_id"]) <= set(data.students["id"])
    assert set(data.lms_events["student_id"]) <= set(data.students["id"])
    assert set(data.students["section_id"]) <= set(data.sections["id"])
    assert set(data.sections["term_id"]) <= set(data.terms["id"])


def test_missing_file_raises(oulad_dir: Path) -> None:
    (oulad_dir / "studentVle.csv").unlink()
    with pytest.raises(ValueError, match="missing"):
        load_oulad(oulad_dir)


def test_missing_column_raises(oulad_dir: Path) -> None:
    (oulad_dir / "courses.csv").write_text("code_module,code_presentation\nAAA,2013J\n")
    with pytest.raises(ValueError, match="module_presentation_length"):
        load_oulad(oulad_dir)


def test_unknown_presentation_code_in_data_raises(oulad_dir: Path) -> None:
    (oulad_dir / "studentInfo.csv").write_text(INFO.replace("BBB,2013J", "BBB,2013Z"))
    with pytest.raises(ValueError, match="presentation code"):
        load_oulad(oulad_dir)
