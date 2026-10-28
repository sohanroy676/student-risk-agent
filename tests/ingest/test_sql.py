"""SQL text and row conversion, checked without a database."""

import importlib.util
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.ingest.clean import clean
from app.ingest.db import _records, _upsert_sql
from app.ingest.schema import SPEC_BY_NAME, SPECS

MIGRATION = Path("app/db/migrations/versions/0002_raw_tables_and_dq_reports.py")


def test_upsert_updates_non_key_columns() -> None:
    sql = _upsert_sql("core", SPEC_BY_NAME["marks"])
    assert sql == (
        "INSERT INTO core.marks (assessment_id, student_id, marks_obtained, submitted_on) "
        "VALUES (:assessment_id, :student_id, :marks_obtained, :submitted_on) "
        "ON CONFLICT (assessment_id, student_id) DO UPDATE SET "
        "marks_obtained = EXCLUDED.marks_obtained, submitted_on = EXCLUDED.submitted_on"
    )


def test_upsert_with_only_key_columns_does_nothing_on_conflict() -> None:
    assert _upsert_sql("core", SPEC_BY_NAME["enrollments"]).endswith("DO NOTHING")
    assert _upsert_sql("core", SPEC_BY_NAME["lms_events"]).endswith("DO NOTHING")


def test_raw_migration_matches_the_specs() -> None:
    loader = importlib.util.spec_from_file_location("m0002", MIGRATION)
    assert loader is not None and loader.loader is not None
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    assert set(module.RAW_TABLES) == {s.name for s in SPECS}
    for spec in SPECS:
        columns, key = module.RAW_TABLES[spec.name]
        assert list(columns) == spec.column_names
        assert key == spec.key


def test_records_are_plain_python_with_none_for_missing(
    good: Callable[..., dict[str, pd.DataFrame]],
) -> None:
    tables = clean(good(), date(2026, 2, 1)).tables
    marks = _records(tables["marks"], SPEC_BY_NAME["marks"])
    assert marks[0] == {
        "assessment_id": 1,
        "student_id": 1,
        "marks_obtained": 70.0,
        "submitted_on": date(2026, 1, 30),
    }
    assert marks[1]["marks_obtained"] is None and marks[1]["submitted_on"] is None
    assert type(marks[0]["assessment_id"]) is int
    attendance = _records(tables["attendance"], SPEC_BY_NAME["attendance"])
    assert attendance[0]["present"] is True
    events = _records(tables["lms_events"], SPEC_BY_NAME["lms_events"])
    assert events[0]["occurred_at"] == datetime(2026, 1, 30, 14, 0)
    assert type(events[0]["occurred_at"]) is datetime
