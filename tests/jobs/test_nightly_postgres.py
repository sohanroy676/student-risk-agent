"""The whole night against real Postgres (skipped without TEST_DATABASE_URL; CI runs it)."""

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text

from app.core.audit_store import verify
from app.jobs.nightly import DataQualityFailed, run_pipeline
from app.ml.calibrate import CalibratedModel
from app.ml.gate import Metrics
from app.ml.registry import Registry
from data.synthetic import generator

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")

AS_OF = generator.TERM_START + timedelta(weeks=8, days=2)
MENTORS = 10
GOOD = Metrics(0.74, 0.02, {"gender": 0.03})


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
def engine() -> Iterator[Engine]:
    assert TEST_DB is not None
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    eng = create_engine(TEST_DB)
    try:
        yield eng
    finally:
        eng.dispose()
        _alembic("downgrade", "base")


@pytest.fixture
def csv_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "erp"
    generator.write_csv(generator.generate(seed=3), folder)
    return folder


@pytest.fixture
def registry(tmp_path: Path, model: CalibratedModel) -> Registry:
    store = Registry(tmp_path / "mlruns")
    versions = store.log_release(dict.fromkeys((4, 8), model), GOOD, {"model": "lgbm"}, "# card")
    assert store.promote(versions, GOOD).passed
    return store


def _assign_mentors(engine: Engine) -> None:
    """Assign after the first load: students only exist once the CSVs are ingested."""
    with engine.begin() as conn:
        ids = conn.execute(text("SELECT id FROM core.students ORDER BY id")).scalars().all()
        conn.execute(text("DELETE FROM app.mentor_assignments"))
        conn.execute(
            text("INSERT INTO app.mentor_assignments VALUES (:s, :m)"),
            [{"s": s, "m": f"m{s % MENTORS}"} for s in ids],
        )


def _count(engine: Engine, sql: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def _night(engine: Engine, csv_dir: Path, registry: Registry) -> Any:
    return run_pipeline(engine, csv_dir, registry, AS_OF)


def test_a_night_scores_everyone_opens_capped_cases_and_writes_reasons(
    engine: Engine, csv_dir: Path, registry: Registry
) -> None:
    _night(engine, csv_dir, registry)  # first night loads students; nobody has a mentor yet
    assert _count(engine, "SELECT count(*) FROM app.cases") == 0
    _assign_mentors(engine)
    summary = _night(engine, csv_dir, registry)

    assert summary.data_quality in ("ok", "warn") and summary.skipped is None
    assert summary.model_week == 8
    assert summary.scored == generator.N_STUDENTS
    assert _count(engine, "SELECT count(*) FROM app.risk_scores") == generator.N_STUDENTS
    assert 0 < summary.opened <= 3 * MENTORS
    assert _count(engine, "SELECT count(*) FROM app.cases") == summary.opened
    assert (
        _count(engine, "SELECT max(n) FROM (SELECT count(*) n FROM app.cases GROUP BY mentor_id) c")
        <= 3
    )

    assert summary.reasons > 0 and summary.reasons <= 3 * summary.opened
    assert (
        _count(engine, "SELECT count(*) FROM app.case_reasons WHERE fact_id NOT LIKE 'case-%'") == 0
    )
    assert _count(engine, "SELECT count(DISTINCT case_id) FROM app.case_reasons") <= summary.opened
    # reasons exist only for cases, never for green students
    assert (
        _count(
            engine,
            "SELECT count(*) FROM app.case_reasons r JOIN app.cases c ON c.id = r.case_id "
            "WHERE c.band NOT IN ('amber', 'red')",
        )
        == 0
    )


def test_mentors_from_the_csv_feed_the_first_night_with_no_manual_step(
    engine: Engine, csv_dir: Path, registry: Registry
) -> None:
    lines = ["student_id,mentor_id"] + [
        f"{s},m{s % MENTORS}" for s in range(1, generator.N_STUDENTS + 1)
    ]
    (csv_dir / "mentor_assignments.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = _night(engine, csv_dir, registry)
    assert summary.unassigned == 0
    assert 0 < summary.opened <= 3 * MENTORS
    assert _count(engine, "SELECT count(*) FROM app.mentor_assignments") == generator.N_STUDENTS
    assert _count(engine, "SELECT count(DISTINCT mentor_id) FROM app.cases") > 1


def test_running_the_same_night_twice_changes_nothing(
    engine: Engine, csv_dir: Path, registry: Registry
) -> None:
    _night(engine, csv_dir, registry)
    _assign_mentors(engine)
    _night(engine, csv_dir, registry)
    tables = ("app.risk_scores", "app.cases", "app.case_events", "app.case_reasons")
    before = {t: _count(engine, f"SELECT count(*) FROM {t}") for t in tables}  # noqa: S608
    _night(engine, csv_dir, registry)
    assert {t: _count(engine, f"SELECT count(*) FROM {t}") for t in tables} == before  # noqa: S608


def test_a_failed_data_quality_check_stops_before_scoring(
    engine: Engine, csv_dir: Path, registry: Registry
) -> None:
    students = csv_dir / "students.csv"
    students.write_text(students.read_text().splitlines()[0] + "\n")  # header only
    with pytest.raises(DataQualityFailed):
        _night(engine, csv_dir, registry)
    assert _count(engine, "SELECT count(*) FROM raw.dq_reports") == 1  # the report is kept
    assert _count(engine, "SELECT count(*) FROM core.students") == 0
    assert _count(engine, "SELECT count(*) FROM app.risk_scores") == 0
    halted = "SELECT count(*) FROM gov.audit_log WHERE action = 'nightly.halted'"
    assert _count(engine, halted) == 1
    assert _count(engine, "SELECT count(*) FROM gov.audit_log WHERE action = 'nightly.run'") == 0


def test_the_night_is_audited_and_the_chain_verifies(
    engine: Engine, csv_dir: Path, registry: Registry
) -> None:
    _night(engine, csv_dir, registry)
    _assign_mentors(engine)
    summary = _night(engine, csv_dir, registry)
    with engine.connect() as conn:
        result = verify(conn)
    assert result.ok
    opened = "SELECT count(*) FROM gov.audit_log WHERE action = 'case.opened'"
    assert _count(engine, opened) == summary.opened
    runs = "SELECT count(*) FROM gov.audit_log WHERE action = 'nightly.run'"
    assert _count(engine, runs) == 2  # a re-run is itself something that happened
    with engine.connect() as conn:
        detail = conn.execute(
            text("SELECT detail FROM gov.audit_log WHERE action = 'nightly.run' ORDER BY seq DESC")
        ).scalar()
    assert detail["cases_opened"] == summary.opened
    assert not any(banned in key for key in detail for banned in ("score", "band", "probab"))


def test_a_night_outside_any_term_scores_nothing_but_still_succeeds(
    engine: Engine, csv_dir: Path, registry: Registry
) -> None:
    summary = run_pipeline(engine, csv_dir, registry, generator.TERM_END + timedelta(days=60))
    assert summary.skipped == "no active term" and summary.scored == 0
    assert _count(engine, "SELECT count(*) FROM app.risk_scores") == 0


def test_a_missing_production_model_fails_loudly_and_writes_nothing(
    engine: Engine, csv_dir: Path, tmp_path: Path
) -> None:
    from app.ml.registry import NoProductionModel

    with pytest.raises(NoProductionModel):
        _night(engine, csv_dir, Registry(tmp_path / "empty"))
    assert _count(engine, "SELECT count(*) FROM app.risk_scores") == 0


BUDGET_S = 30 * 60


def test_a_night_on_five_thousand_students_fits_the_thirty_minute_budget(
    engine: Engine, tmp_path: Path, registry: Registry, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "erp5000"
    generator.write_csv(generator.generate(seed=1, n_students=5000), folder)
    _night(engine, folder, registry)  # first night: loads students and history
    _assign_mentors(engine)
    started = time.perf_counter()
    summary = _night(engine, folder, registry)  # a normal night: re-ingest, score, cases
    elapsed = time.perf_counter() - started
    with capsys.disabled():  # so the number shows in the CI log of a passing run
        print(f"\nnightly run on 5,000 students: {elapsed:.0f} s")
    assert summary.scored == 5000
    assert summary.opened > 0 and summary.reasons > 0
    assert elapsed < BUDGET_S, f"{elapsed:.0f} s exceeds the {BUDGET_S} s budget"
