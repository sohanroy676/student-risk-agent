"""What the CSV connector expects: one `TableSpec` per source file.

The same specs drive the reader, the cleaner, the data-quality report and the SQL upserts,
so a column added here shows up in all of them. The raw tables in migration 0002 repeat the
column names by hand (migrations must not change when this file does).
"""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["int", "text", "date", "datetime", "bool", "num"]


@dataclass(frozen=True)
class Column:
    name: str
    kind: Kind
    required: bool = True
    # Smallest allowed value for "num" columns; `positive` makes it exclusive.
    minimum: float | None = None
    positive: bool = False


@dataclass(frozen=True)
class TableSpec:
    name: str
    schema: str
    columns: tuple[Column, ...]
    key: tuple[str, ...]
    # column -> parent table whose key column must contain the value
    parents: tuple[tuple[str, str], ...] = ()
    unique: tuple[str, ...] = ()

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


def _ints(*names: str) -> tuple[Column, ...]:
    return tuple(Column(n, "int") for n in names)


SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        "terms",
        "core",
        (
            Column("id", "int"),
            Column("name", "text"),
            Column("start_date", "date"),
            Column("end_date", "date"),
        ),
        key=("id",),
    ),
    TableSpec(
        "sections",
        "core",
        (Column("id", "int"), Column("name", "text"), Column("term_id", "int")),
        key=("id",),
        parents=(("term_id", "terms"),),
    ),
    TableSpec(
        "courses",
        "core",
        (Column("id", "int"), Column("code", "text"), Column("title", "text")),
        key=("id",),
        unique=("code",),
    ),
    TableSpec(
        "students",
        "core",
        _ints("id", "section_id"),
        key=("id",),
        parents=(("section_id", "sections"),),
    ),
    TableSpec(
        "enrollments",
        "core",
        _ints("student_id", "course_id"),
        key=("student_id", "course_id"),
        parents=(("student_id", "students"), ("course_id", "courses")),
    ),
    TableSpec(
        "attendance",
        "core",
        (
            Column("student_id", "int"),
            Column("course_id", "int"),
            Column("class_date", "date"),
            Column("present", "bool"),
        ),
        key=("student_id", "course_id", "class_date"),
        parents=(("student_id", "students"), ("course_id", "courses")),
    ),
    TableSpec(
        "assessments",
        "core",
        (
            Column("id", "int"),
            Column("course_id", "int"),
            Column("title", "text"),
            Column("due_date", "date"),
            Column("max_marks", "num", positive=True, minimum=0),
        ),
        key=("id",),
        parents=(("course_id", "courses"),),
    ),
    TableSpec(
        "marks",
        "core",
        (
            Column("assessment_id", "int"),
            Column("student_id", "int"),
            Column("marks_obtained", "num", required=False, minimum=0),
            Column("submitted_on", "date", required=False),
        ),
        key=("assessment_id", "student_id"),
        parents=(("assessment_id", "assessments"), ("student_id", "students")),
    ),
    TableSpec(
        "fees",
        "core",
        (
            Column("id", "int"),
            Column("student_id", "int"),
            Column("due_date", "date"),
            Column("amount", "num", positive=True, minimum=0),
            Column("paid_on", "date", required=False),
        ),
        key=("id",),
        parents=(("student_id", "students"),),
    ),
    TableSpec(
        "lms_events",
        "core",
        (
            Column("student_id", "int"),
            Column("course_id", "int"),
            Column("occurred_at", "datetime"),
            Column("event_type", "text"),
        ),
        key=("student_id", "course_id", "occurred_at", "event_type"),
        parents=(("student_id", "students"), ("course_id", "courses")),
    ),
    # Protected attributes: loaded to `restricted` only, never part of `CoreTables`.
    TableSpec(
        "student_attributes",
        "restricted",
        (Column("student_id", "int"), Column("gender", "text"), Column("category", "text")),
        key=("student_id",),
        parents=(("student_id", "students"),),
    ),
    # Who mentors whom: the case engine opens a case only for a student listed here. The mentor
    # id is the mentor's login subject, kept as the exact text the file gives (trimmed).
    TableSpec(
        "mentor_assignments",
        "app",
        (Column("student_id", "int"), Column("mentor_id", "text")),
        key=("student_id",),
        parents=(("student_id", "students"),),
    ),
)

SPEC_BY_NAME = {s.name: s for s in SPECS}
# Tables that must have rows for a night's data to be usable at all.
ESSENTIAL = ("students", "enrollments", "attendance", "marks")
# Date column used to judge how fresh a table is.
FRESHNESS = {
    "attendance": "class_date",
    "marks": "submitted_on",
    "lms_events": "occurred_at",
    "fees": "paid_on",
}
# Tables that should gain rows every few days; marks and fees arrive in bursts, so their
# newest date says nothing about whether the feed is alive.
STREAMING = ("attendance", "lms_events")
