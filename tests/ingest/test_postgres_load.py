import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.ingest.csv_connector import ingest_csv_dir
from app.ingest.schema import SPECS
from data.synthetic import generator

TEST_DB = os.environ.get("TEST_DATABASE_URL")
RUN = date(2026, 4, 20)
COHORT = 60  # enough for every assertion here; the 5,000-student test covers scale

pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")


def _alembic(*args: str) -> None:
    assert TEST_DB is not None
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": TEST_DB},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr


@pytest.fixture
def empty_db() -> Iterator[str]:
    assert TEST_DB is not None
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    yield TEST_DB
    _alembic("downgrade", "base")


def _counts(url: str) -> dict[str, int]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                f"{schema}.{spec.name}": int(
                    conn.execute(text(f"SELECT count(*) FROM {schema}.{spec.name}")).scalar_one()  # noqa: S608
                )
                for spec in SPECS
                for schema in ("raw", spec.schema)
            }
    finally:
        engine.dispose()


def test_loading_the_same_files_twice_changes_nothing(empty_db: str, tmp_path: Path) -> None:
    data = generator.generate(seed=3, n_students=COHORT)
    generator.write_csv(data, tmp_path)
    first = ingest_csv_dir(empty_db, tmp_path, RUN)
    after_first = _counts(empty_db)
    second = ingest_csv_dir(empty_db, tmp_path, RUN)
    assert first.status == second.status == "ok"
    assert _counts(empty_db) == after_first
    assert after_first["core.students"] == len(data.tables["students"].rows)
    assert after_first["core.attendance"] == len(data.tables["attendance"].rows)
    assert after_first["restricted.student_attributes"] == len(data.tables["students"].rows)
    engine = create_engine(empty_db)
    try:
        with engine.connect() as conn:
            reports = conn.execute(text("SELECT count(*) FROM raw.dq_reports")).scalar_one()
    finally:
        engine.dispose()
    assert reports == 1


def test_a_corrected_value_updates_in_place(empty_db: str, tmp_path: Path) -> None:
    generator.write_csv(generator.generate(seed=3, n_students=COHORT), tmp_path)
    ingest_csv_dir(empty_db, tmp_path, RUN)
    path = tmp_path / "courses.csv"
    path.write_text(path.read_text().replace("Course 1", "Renamed"), encoding="utf-8")
    ingest_csv_dir(empty_db, tmp_path, RUN)
    engine = create_engine(empty_db)
    try:
        with engine.connect() as conn:
            titles = (
                conn.execute(text("SELECT title FROM core.courses WHERE id = 1")).scalars().all()
            )
            raw_titles = (
                conn.execute(text("SELECT title FROM raw.courses WHERE id = '1'")).scalars().all()
            )
    finally:
        engine.dispose()
    assert titles == raw_titles == ["Renamed"]


def test_a_failing_night_stores_raw_and_report_but_not_core(empty_db: str, tmp_path: Path) -> None:
    generator.write_csv(generator.generate(seed=3, n_students=COHORT), tmp_path)
    (tmp_path / "attendance.csv").write_text("student_id,course_id,class_date,present\n")
    report = ingest_csv_dir(empty_db, tmp_path, RUN)
    assert report.status == "fail"
    counts = _counts(empty_db)
    assert counts["raw.students"] > 0
    assert counts["core.students"] == 0
    engine = create_engine(empty_db)
    try:
        with engine.connect() as conn:
            status = conn.execute(text("SELECT status FROM raw.dq_reports")).scalar_one()
    finally:
        engine.dispose()
    assert status == "fail"


def test_migration_0002_downgrades_and_upgrades_again(empty_db: str) -> None:
    _alembic("downgrade", "0001")
    _alembic("upgrade", "head")


def _query(url: str, sql: str) -> list[tuple[object, ...]]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(text(sql)).all()]
    finally:
        engine.dispose()


def _write_mentors(folder: Path, rows: dict[int, str]) -> None:
    lines = ["student_id,mentor_id", *(f"{s},{m}" for s, m in rows.items())]
    (folder / "mentor_assignments.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_mentor_assignments_load_and_reloading_changes_nothing(
    empty_db: str, tmp_path: Path
) -> None:
    generator.write_csv(generator.generate(seed=3, n_students=COHORT), tmp_path)
    _write_mentors(tmp_path, {1: "m1", 2: "m1", 3: "m2"})
    assert ingest_csv_dir(empty_db, tmp_path, RUN).status == "ok"
    mentors = "SELECT student_id, mentor_id FROM app.mentor_assignments ORDER BY 1"
    assert _query(empty_db, mentors) == [(1, "m1"), (2, "m1"), (3, "m2")]
    assert _query(empty_db, "SELECT count(*) FROM raw.mentor_assignments") == [(3,)]
    audited = "SELECT detail FROM gov.audit_log WHERE action = 'mentor_assignments.loaded'"
    first = _query(empty_db, audited)
    assert len(first) == 1 and first[0][0]["added"] == 3 and first[0][0]["changed"] == 0  # type: ignore[index]
    ingest_csv_dir(empty_db, tmp_path, RUN)
    assert _query(empty_db, mentors) == [(1, "m1"), (2, "m1"), (3, "m2")]
    assert len(_query(empty_db, audited)) == 1  # nothing changed, so nothing to record


def test_reassigning_a_student_updates_the_mentor_and_is_audited(
    empty_db: str, tmp_path: Path
) -> None:
    generator.write_csv(generator.generate(seed=3, n_students=COHORT), tmp_path)
    _write_mentors(tmp_path, {1: "m1", 2: "m1"})
    ingest_csv_dir(empty_db, tmp_path, RUN)
    _write_mentors(tmp_path, {1: "m2", 2: "m1", 3: "m3"})
    ingest_csv_dir(empty_db, tmp_path, RUN)
    mentors = "SELECT student_id, mentor_id FROM app.mentor_assignments ORDER BY 1"
    assert _query(empty_db, mentors) == [(1, "m2"), (2, "m1"), (3, "m3")]
    details = _query(
        empty_db,
        "SELECT detail FROM gov.audit_log WHERE action = 'mentor_assignments.loaded' ORDER BY seq",
    )
    assert [(d[0]["added"], d[0]["changed"]) for d in details] == [(2, 0), (1, 1)]  # type: ignore[index]
    # who got whom is in the table, not the log: only counts and the source are recorded
    assert all(set(d[0]) == {"source", "added", "changed"} for d in details)  # type: ignore[call-overload]


def test_a_file_that_omits_a_student_leaves_their_assignment_alone(
    empty_db: str, tmp_path: Path
) -> None:
    generator.write_csv(generator.generate(seed=3, n_students=COHORT), tmp_path)
    _write_mentors(tmp_path, {1: "m1", 2: "m1"})
    ingest_csv_dir(empty_db, tmp_path, RUN)
    _write_mentors(tmp_path, {2: "m2"})
    ingest_csv_dir(empty_db, tmp_path, RUN)
    mentors = "SELECT student_id, mentor_id FROM app.mentor_assignments ORDER BY 1"
    assert _query(empty_db, mentors) == [(1, "m1"), (2, "m2")]


def test_a_failing_night_changes_no_assignment(empty_db: str, tmp_path: Path) -> None:
    generator.write_csv(generator.generate(seed=3, n_students=COHORT), tmp_path)
    _write_mentors(tmp_path, {1: "m1"})
    ingest_csv_dir(empty_db, tmp_path, RUN)
    _write_mentors(tmp_path, {1: "m9"})
    (tmp_path / "attendance.csv").write_text("student_id,course_id,class_date,present\n")
    assert ingest_csv_dir(empty_db, tmp_path, RUN).status == "fail"
    assert _query(empty_db, "SELECT mentor_id FROM app.mentor_assignments") == [("m1",)]


def test_migration_0006_downgrades_and_upgrades_again(empty_db: str) -> None:
    _alembic("downgrade", "0005")
    assert _query(empty_db, "SELECT to_regclass('raw.mentor_assignments')") == [(None,)]
    _alembic("upgrade", "head")
    assert _query(empty_db, "SELECT count(*) FROM raw.mentor_assignments") == [(0,)]
