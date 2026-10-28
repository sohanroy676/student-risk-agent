from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd
import pytest

from app.ingest.clean import ROW
from app.ingest.schema import SPEC_BY_NAME

Rows = Sequence[Mapping[str, Any]]

GOOD: dict[str, Rows] = {
    "terms": [{"id": 1, "name": "T1", "start_date": "2026-01-05", "end_date": "2026-04-19"}],
    "sections": [{"id": 1, "name": "A", "term_id": 1}],
    "courses": [
        {"id": 1, "code": "CS101", "title": "Intro"},
        {"id": 2, "code": "CS102", "title": "Next"},
    ],
    "students": [{"id": 1, "section_id": 1}, {"id": 2, "section_id": 1}],
    "enrollments": [
        {"student_id": 1, "course_id": 1},
        {"student_id": 2, "course_id": 1},
    ],
    "attendance": [
        {"student_id": 1, "course_id": 1, "class_date": "2026-01-30", "present": "True"},
        {"student_id": 2, "course_id": 1, "class_date": "2026-01-30", "present": "False"},
    ],
    "assessments": [
        {"id": 1, "course_id": 1, "title": "Quiz", "due_date": "2026-01-30", "max_marks": 100}
    ],
    "marks": [
        {"assessment_id": 1, "student_id": 1, "marks_obtained": 70, "submitted_on": "2026-01-30"},
        {"assessment_id": 1, "student_id": 2, "marks_obtained": "", "submitted_on": ""},
    ],
    "fees": [{"id": 1, "student_id": 1, "due_date": "2026-01-12", "amount": 45000, "paid_on": ""}],
    "lms_events": [
        {
            "student_id": 1,
            "course_id": 1,
            "occurred_at": "2026-01-30 14:00:00",
            "event_type": "quiz_attempt",
        }
    ],
    "student_attributes": [{"student_id": 1, "gender": "F", "category": "general"}],
}


def to_raw(tables: Mapping[str, Rows]) -> dict[str, pd.DataFrame]:
    """Raw text frames as the reader would produce them (`_row` = line number)."""
    out: dict[str, pd.DataFrame] = {}
    for name, rows in tables.items():
        columns = SPEC_BY_NAME[name].column_names
        frame = pd.DataFrame(
            [{c: str(r.get(c, "")) for c in columns} for r in rows], columns=columns
        )
        frame[ROW] = range(2, len(frame) + 2)
        out[name] = frame
    return out


@pytest.fixture
def good() -> Callable[..., dict[str, pd.DataFrame]]:
    """Build raw frames from the good fixture, replacing whole tables by keyword."""

    def build(**replace: Rows) -> dict[str, pd.DataFrame]:
        return to_raw({**GOOD, **replace})

    return build
