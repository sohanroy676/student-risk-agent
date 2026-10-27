"""Core-shaped input tables for the feature builder.

The same frames come from the database (`app.features.db`), the OULAD loader and the
synthetic generator, so one feature implementation serves training and nightly scoring.
There is deliberately no field for protected attributes: they cannot reach a feature.
"""

from dataclasses import dataclass

import pandas as pd

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "enrollments": {"student_id", "course_id"},
    "attendance": {"student_id", "course_id", "class_date", "present"},
    "assessments": {"id", "course_id", "due_date", "max_marks"},
    "marks": {"assessment_id", "student_id", "marks_obtained", "submitted_on"},
    "fees": {"student_id", "due_date", "amount", "paid_on"},
    "lms_events": {"student_id", "course_id", "occurred_at"},
}
CONTEXT_COLUMNS = {"student_id", "credits_enrolled", "prior_attempts"}
DATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "attendance": ("class_date",),
    "assessments": ("due_date",),
    "marks": ("submitted_on",),
    "fees": ("due_date", "paid_on"),
    "lms_events": ("occurred_at",),
}


@dataclass
class CoreTables:
    enrollments: pd.DataFrame
    attendance: pd.DataFrame
    assessments: pd.DataFrame
    marks: pd.DataFrame
    fees: pd.DataFrame
    lms_events: pd.DataFrame
    # Undated facts fixed at enrolment (credit load, earlier attempts); optional.
    student_context: pd.DataFrame | None = None

    @classmethod
    def from_frames(cls, **frames: pd.DataFrame) -> "CoreTables":
        """Validate columns and coerce date columns; extra columns/tables are ignored."""
        missing_tables = REQUIRED_COLUMNS.keys() - frames.keys()
        if missing_tables:
            raise ValueError(f"Missing tables: {sorted(missing_tables)}")
        clean: dict[str, pd.DataFrame] = {}
        for name, required in REQUIRED_COLUMNS.items():
            frame = frames[name].copy()
            missing = required - set(frame.columns)
            if missing:
                raise ValueError(f"{name} is missing columns: {sorted(missing)}")
            for column in DATE_COLUMNS.get(name, ()):
                frame[column] = pd.to_datetime(frame[column])
            clean[name] = frame
        context = frames.get("student_context")
        if context is not None:
            missing = CONTEXT_COLUMNS - set(context.columns)
            if missing:
                raise ValueError(f"student_context is missing columns: {sorted(missing)}")
            context = context.copy()
        return cls(**clean, student_context=context)
