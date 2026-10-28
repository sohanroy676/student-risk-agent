from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.features.snapshot import build_snapshot
from app.ingest.oulad import ACTIVITY_EVENT_TYPES, load_oulad, presentation_start


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
    info = oulad_dir / "studentInfo.csv"
    info.write_text(info.read_text().replace("BBB,2013J", "BBB,2013Z"))
    with pytest.raises(ValueError, match="presentation code"):
        load_oulad(oulad_dir)


def test_each_presentation_is_its_own_course(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    assert sorted(data.courses["code"]) == ["AAA-2013J", "AAA-2014J", "BBB-2013J"]
    code_of = data.courses.set_index("id")["code"]
    assessment_course = data.assessments.set_index("id")["course_id"].map(code_of)
    assert assessment_course.loc[10] == "AAA-2013J"
    assert assessment_course.loc[12] == "AAA-2014J"
    # No student is enrolled in an offering other than their own presentation's.
    assert len(data.enrollments) == len(data.students)
    assert data.enrollments["student_id"].is_unique


def test_labels_carry_term_start_and_no_registration_file_means_never_left(
    oulad_dir: Path,
) -> None:
    labels = load_oulad(oulad_dir).labels
    assert set(labels["term_start"]) == {pd.Timestamp("2013-10-01"), pd.Timestamp("2014-10-01")}
    assert labels["unregistered_on"].isna().all()


def test_unregistration_offsets_become_dates(oulad_dir: Path) -> None:
    (oulad_dir / "studentRegistration.csv").write_text(
        "code_module,code_presentation,id_student,date_registration,date_unregistration\n"
        "AAA,2013J,1,-30,\n"
        "AAA,2013J,2,-10,30\n"
        "AAA,2014J,1,-5,-2\n"
        "BBB,2013J,3,-1,\n"
    )
    labels = load_oulad(oulad_dir).labels
    left = labels["unregistered_on"].dropna()
    assert sorted(left) == [pd.Timestamp("2013-10-31"), pd.Timestamp("2014-09-29")]
    assert labels["unregistered_on"].isna().sum() == 2


def test_registration_file_missing_column_raises(oulad_dir: Path) -> None:
    (oulad_dir / "studentRegistration.csv").write_text("code_module,id_student\nAAA,1\n")
    with pytest.raises(ValueError, match="date_unregistration"):
        load_oulad(oulad_dir)


def test_to_core_tables_feeds_the_snapshot_builder(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    snap = build_snapshot(data.to_core_tables(), data.students["id"], date(2013, 10, 20))
    assert len(snap) == len(data.students)
    assert snap["classes_held"].eq(0).all()  # OULAD has no attendance
    assert snap["lms_events_total"].sum() > 0


def test_question_mark_means_missing_as_in_the_published_files(oulad_dir: Path) -> None:
    (oulad_dir / "studentRegistration.csv").write_text(
        '"code_module","code_presentation","id_student","date_registration","date_unregistration"\n'
        '"AAA","2013J","1","-30","?"\n'
        '"AAA","2013J","2","-10","30"\n'
    )
    assessments = oulad_dir / "assessments.csv"
    assessments.write_text(assessments.read_text().replace(",,100", ",?,100"))
    scores = oulad_dir / "studentAssessment.csv"
    scores.write_text(scores.read_text().replace("25,0,\n", "25,0,?\n"))
    data = load_oulad(oulad_dir)
    assert data.labels["unregistered_on"].notna().sum() == 1
    exam_due = data.assessments.set_index("id").loc[11, "due_date"]
    assert exam_due == pd.Timestamp("2013-10-01") + pd.Timedelta(days=268)
    assert data.marks["marks_obtained"].isna().sum() == 1


def test_vle_activity_types_become_event_types(oulad_dir: Path) -> None:
    (oulad_dir / "vle.csv").write_text(
        "id_site,code_module,code_presentation,activity_type,week_from,week_to\n"
        "500,AAA,2013J,forumng,,\n"
        "501,AAA,2013J,quiz,,\n"
        "500,AAA,2014J,resource,,\n"
        "502,BBB,2013J,oucontent,,\n"
    )
    events = load_oulad(oulad_dir).lms_events
    assert sorted(events["event_type"]) == ["content", "content", "forum_post", "quiz_attempt"]


def test_all_vle_activity_types_are_grouped(oulad_dir: Path) -> None:
    expected = {
        "forumng": "forum_post",
        "quiz": "quiz_attempt",
        "externalquiz": "quiz_attempt",
        "oucontent": "content",
        "resource": "content",
        "page": "content",
        "subpage": "content",
        "sharedsubpage": "content",
        "folder": "content",
        "homepage": "homepage",
        "url": "url",
        "oucollaborate": "collab",
        "ouelluminate": "collab",
        "ouwiki": "wiki_glossary",
        "glossary": "wiki_glossary",
        "dataplus": "wiki_glossary",
        "htmlactivity": "activity",
        "repeatactivity": "activity",
        "questionnaire": "activity",
        "dualpane": "activity",
    }
    assert expected == ACTIVITY_EVENT_TYPES  # the 20 types in the published vle.csv
    (oulad_dir / "vle.csv").write_text(
        "id_site,code_module,code_presentation,activity_type\n"
        "500,AAA,2013J,externalquiz\n"
        "501,AAA,2013J,homepage\n"
        "500,AAA,2014J,somethingnew\n"
        "502,BBB,2013J,url\n"
    )
    events = load_oulad(oulad_dir).lms_events
    assert sorted(events["event_type"]) == ["homepage", "quiz_attempt", "url", "view"]


def test_without_vle_file_every_click_is_a_view(oulad_dir: Path) -> None:
    assert set(load_oulad(oulad_dir).lms_events["event_type"]) == {"view"}


def test_vle_file_missing_column_raises(oulad_dir: Path) -> None:
    (oulad_dir / "vle.csv").write_text("id_site,code_module\n500,AAA\n")
    with pytest.raises(ValueError, match="activity_type"):
        load_oulad(oulad_dir)


def test_site_ids_are_scoped_to_their_presentation(oulad_dir: Path) -> None:
    # Site 500 is a forum in 2013J but a plain resource in 2014J.
    (oulad_dir / "vle.csv").write_text(
        "id_site,code_module,code_presentation,activity_type\n"
        "500,AAA,2013J,forumng\n"
        "500,AAA,2014J,resource\n"
    )
    events = load_oulad(oulad_dir).lms_events
    forum = events[events["event_type"] == "forum_post"]
    assert len(forum) == 1
    assert forum["occurred_at"].iloc[0] == pd.Timestamp("2013-10-01") - pd.Timedelta(days=5)


def test_context_comes_from_credits_and_prior_attempts(oulad_dir: Path) -> None:
    data = load_oulad(oulad_dir)
    assert set(data.context.columns) == {"student_id", "credits_enrolled", "prior_attempts"}
    assert len(data.context) == len(data.students)
    assert data.context["prior_attempts"].max() == 1  # AAA 2014J student 1 retook the module
    snap = build_snapshot(data.to_core_tables(), data.students["id"], date(2013, 10, 20))
    assert snap["credits_enrolled"].eq(60).all()
