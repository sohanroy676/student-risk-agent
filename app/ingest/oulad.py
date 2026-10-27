"""Load the Open University Learning Analytics Dataset (OULAD) into core-shaped frames.

OULAD dates are day offsets from the presentation start (day 0), so each presentation
is given an assumed calendar start date and offsets are converted to real dates. That
lets the same `as_of` feature code serve OULAD, the synthetic college and the ERP.

A "student" is one registration: a surrogate id per (module, presentation, id_student),
because the same person can take several presentations. Protected attributes are kept
in a separate frame and never merged into the core tables.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Assumed calendar start of each presentation; B starts in February, J in October.
PRESENTATION_STARTS = {"B": (2, 1), "J": (10, 1)}
AT_RISK_RESULTS = frozenset({"Withdrawn", "Fail"})
MAX_MARKS = 100

_REQUIRED_COLUMNS = {
    "courses.csv": {"code_module", "code_presentation", "module_presentation_length"},
    "studentInfo.csv": {
        "code_module",
        "code_presentation",
        "id_student",
        "gender",
        "region",
        "highest_education",
        "imd_band",
        "age_band",
        "disability",
        "final_result",
    },
    "assessments.csv": {"code_module", "code_presentation", "id_assessment", "date"},
    "studentAssessment.csv": {
        "id_assessment",
        "id_student",
        "date_submitted",
        "is_banked",
        "score",
    },
    "studentVle.csv": {"code_module", "code_presentation", "id_student", "date", "sum_click"},
}


@dataclass
class OuladData:
    terms: pd.DataFrame
    sections: pd.DataFrame
    courses: pd.DataFrame
    students: pd.DataFrame
    enrollments: pd.DataFrame
    assessments: pd.DataFrame
    marks: pd.DataFrame
    lms_events: pd.DataFrame
    attributes: pd.DataFrame
    labels: pd.DataFrame


def presentation_start(code_presentation: str) -> pd.Timestamp:
    """Assumed start date of a presentation code such as '2013J'."""
    year, suffix = code_presentation[:-1], code_presentation[-1:]
    if not year.isdigit() or suffix not in PRESENTATION_STARTS:
        raise ValueError(f"Unrecognised OULAD presentation code: {code_presentation!r}")
    month, day = PRESENTATION_STARTS[suffix]
    return pd.Timestamp(year=int(year), month=month, day=day)


def _read(directory: Path, name: str) -> pd.DataFrame:
    path = directory / name
    if not path.is_file():
        raise ValueError(f"OULAD file missing: {path}")
    frame = pd.read_csv(path)
    missing = _REQUIRED_COLUMNS[name] - set(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")
    return frame


def _starts(frame: pd.DataFrame) -> pd.Series:
    """Per-row presentation start dates (cached per distinct code)."""
    lookup = {code: presentation_start(code) for code in frame["code_presentation"].unique()}
    return frame["code_presentation"].map(lookup).astype("datetime64[ns]")


def load_oulad(directory: Path) -> OuladData:
    courses_raw = _read(directory, "courses.csv")
    info = _read(directory, "studentInfo.csv")
    assessments_raw = _read(directory, "assessments.csv")
    student_assessment = _read(directory, "studentAssessment.csv")
    vle = _read(directory, "studentVle.csv")

    info = info.drop_duplicates(["code_module", "code_presentation", "id_student"]).reset_index(
        drop=True
    )

    presentations = sorted(info["code_presentation"].unique())
    terms = pd.DataFrame({"id": range(1, len(presentations) + 1), "name": presentations})
    terms["start_date"] = terms["name"].map(presentation_start).astype("datetime64[ns]")
    lengths = courses_raw.groupby("code_presentation")["module_presentation_length"].max()
    terms["end_date"] = terms["start_date"] + pd.to_timedelta(
        terms["name"].map(lengths).fillna(0).astype(int), unit="D"
    )
    term_id = dict(zip(terms["name"], terms["id"], strict=True))

    modules = sorted(info["code_module"].unique())
    courses = pd.DataFrame({"id": range(1, len(modules) + 1), "code": modules, "title": modules})
    course_id = dict(zip(courses["code"], courses["id"], strict=True))

    section_keys = info[["code_module", "code_presentation"]].drop_duplicates()
    sections = section_keys.sort_values(["code_module", "code_presentation"]).reset_index(drop=True)
    sections["id"] = sections.index + 1
    sections["name"] = sections["code_module"] + "-" + sections["code_presentation"]
    sections["term_id"] = sections["code_presentation"].map(term_id)
    section_id = {
        (m, p): i
        for m, p, i in zip(
            sections["code_module"], sections["code_presentation"], sections["id"], strict=True
        )
    }

    info["student_id"] = info.index + 1
    info["section_id"] = [
        section_id[(m, p)]
        for m, p in zip(info["code_module"], info["code_presentation"], strict=True)
    ]
    info["course_id"] = info["code_module"].map(course_id)
    key = ["code_module", "code_presentation", "id_student"]
    student_of = info[[*key, "student_id"]]

    students = info[["student_id", "section_id"]].rename(columns={"student_id": "id"})
    enrollments = info[["student_id", "course_id"]]
    attributes = info[
        [
            "student_id",
            "gender",
            "region",
            "highest_education",
            "imd_band",
            "age_band",
            "disability",
        ]
    ]
    labels = info[["student_id", "code_presentation"]].copy()
    labels["at_risk"] = info["final_result"].isin(AT_RISK_RESULTS)

    # Assessments: exams have no date, so they fall back to the presentation end.
    assessments = assessments_raw.copy()
    assessments["start"] = _starts(assessments)
    end = assessments["code_presentation"].map(
        dict(zip(terms["name"], terms["end_date"], strict=True))
    )
    assessments["due_date"] = (
        assessments["start"] + pd.to_timedelta(assessments["date"], unit="D")
    ).fillna(end)
    assessments["course_id"] = assessments["code_module"].map(course_id)
    assessments["title"] = assessments["id_assessment"].astype(str)
    assessments["max_marks"] = MAX_MARKS
    assessment_start = assessments.set_index("id_assessment")["start"]
    assessment_keys = assessments[["id_assessment", "code_module", "code_presentation"]]

    # Banked results are carried over from an earlier attempt, so they are not dated work.
    work = student_assessment[student_assessment["is_banked"] == 0].merge(
        assessment_keys, on="id_assessment", how="inner"
    )
    work = work.merge(student_of, on=key, how="inner")
    marks = pd.DataFrame(
        {
            "assessment_id": work["id_assessment"],
            "student_id": work["student_id"],
            "marks_obtained": work["score"],
            "submitted_on": work["id_assessment"].map(assessment_start)
            + pd.to_timedelta(work["date_submitted"], unit="D"),
        }
    )

    events = vle.merge(student_of, on=key, how="inner")
    events["occurred_at"] = _starts(events) + pd.to_timedelta(events["date"], unit="D")
    events["course_id"] = events["code_module"].map(course_id)
    lms_events = events[["student_id", "course_id", "occurred_at", "sum_click"]].copy()
    lms_events["event_type"] = "view"

    return OuladData(
        terms=terms[["id", "name", "start_date", "end_date"]],
        sections=sections[["id", "name", "term_id"]],
        courses=courses,
        students=students,
        enrollments=enrollments,
        assessments=assessments[["id_assessment", "course_id", "title", "due_date", "max_marks"]]
        .rename(columns={"id_assessment": "id"})
        .reset_index(drop=True),
        marks=marks.reset_index(drop=True),
        lms_events=lms_events.reset_index(drop=True),
        attributes=attributes.reset_index(drop=True),
        labels=labels.reset_index(drop=True),
    )
