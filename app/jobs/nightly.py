"""The nightly run: ingest, snapshot, score, open cases, write reasons, run the day-7 timers.

`run_pipeline` is the whole night and holds all the logic; the Celery task only wires it to
settings. Everything is point-in-time: features see data dated on or before `as_of` and the
model never receives a protected attribute (`CoreTables` has no path for one).

Scoring, cases, reasons and timers share one transaction, so a night either lands completely or
not at all. A data-quality `fail` stops the night after the raw rows and the report are stored,
and raises, so the failure is visible in the task result. Nothing here contacts a student, and
reasons are stored only for students with an open case (amber or red), for mentors.
"""

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import Connection, Engine, create_engine, text

from app.cases.config import CaseConfig
from app.cases.planner import Score
from app.cases.states import OPEN_STATES
from app.cases.store import run_night, run_timers
from app.core.settings import get_settings
from app.features.db import load_core_tables
from app.features.snapshot import FEATURE_NAMES, build_snapshot
from app.features.tables import CoreTables
from app.ingest.csv_connector import read_csv_dir
from app.ingest.db import ingest
from app.jobs import NIGHTLY_TASK, app
from app.ml.baseline import WEEKS
from app.ml.calibrate import CalibratedModel
from app.ml.explain import contributions, top_reasons
from app.ml.registry import NoProductionModel, Registry

log = logging.getLogger(__name__)

OPEN_VALUES = sorted(s.value for s in OPEN_STATES)


class DataQualityFailed(RuntimeError):
    """The night's data failed its quality check; nothing was scored."""


@dataclass(frozen=True)
class NightSummary:
    """Counts only: no student values, so it is safe to log and to keep as a task result."""

    as_of: str
    data_quality: str
    skipped: str | None
    model_week: int | None
    scored: int
    opened: int
    deferred: int
    unassigned: int
    reasons: int
    moved_to_review: int
    newly_overdue: int


def target_week(term_start: date, as_of: date) -> int:
    """Whole weeks since the term started; the models were trained with week N = start + 7N days."""
    return (as_of - term_start).days // 7


def load_production_model(registry: Registry, week: int) -> tuple[int, CalibratedModel]:
    """The model for the latest trained week at or before `week` (the first week's model before
    that); a week with no production model falls back to an earlier one."""
    candidates = [w for w in reversed(WEEKS) if w <= max(week, WEEKS[0])]
    for candidate in candidates:
        try:
            return candidate, registry.load_production(candidate)
        except NoProductionModel:
            continue
    raise NoProductionModel(f"no production model for week {week} or any earlier week")


def score_students(
    tables: CoreTables, student_ids: Sequence[int], as_of: date, model: CalibratedModel
) -> tuple[pd.DataFrame, list[Score]]:
    """Feature rows (model column order) and calibrated probabilities for the given students."""
    features = build_snapshot(tables, student_ids, as_of)[list(FEATURE_NAMES)]
    if features.empty:
        return features, []
    probabilities = model.predict_proba(features)
    return features, [
        Score(int(student), float(p))
        for student, p in zip(features.index, probabilities, strict=True)
    ]


def reason_rows(
    model: CalibratedModel,
    features: pd.DataFrame,
    case_by_student: dict[int, int],
    as_of: date,
) -> list[dict[str, object]]:
    """Up to three reasons per case, referenced by case id (`case-<id>`), never by student."""
    students = [s for s in case_by_student if s in features.index]
    if not students:
        return []
    rows = features.loc[students].copy()
    rows.index = pd.Index([f"case-{case_by_student[s]}" for s in students])
    found = top_reasons(contributions(model, rows), rows, as_of)
    case_ids = {f"case-{case_id}": case_id for case_id in case_by_student.values()}
    return [
        {
            "case_id": case_ids[str(ref)],
            "as_of": as_of,
            "rank": rank,
            "fact_id": reason.fact_id,
            "feature": reason.feature,
            "value": reason.value,
            "text": reason.text,
        }
        for ref, reasons in found.items()
        for rank, reason in enumerate(reasons, start=1)
    ]


def _store_reasons(
    conn: Connection, rows: list[dict[str, object]], cases: list[int], day: date
) -> None:
    """Replace tonight's reasons for these cases, so a re-run leaves one set."""
    conn.execute(
        text("DELETE FROM app.case_reasons WHERE as_of = :day AND case_id = ANY(:cases)"),
        {"day": day, "cases": cases},
    )
    if rows:
        conn.execute(
            text(
                "INSERT INTO app.case_reasons "
                "(case_id, as_of, rank, fact_id, feature, value, text) "
                "VALUES (:case_id, :as_of, :rank, :fact_id, :feature, :value, :text)"
            ),
            rows,
        )


def _open_cases(conn: Connection, student_ids: list[int]) -> dict[int, int]:
    found = conn.execute(
        text(
            "SELECT student_id, id FROM app.cases "
            "WHERE state = ANY(:open) AND student_id = ANY(:ids)"
        ),
        {"open": OPEN_VALUES, "ids": student_ids},
    )
    return {int(student): int(case) for student, case in found.tuples()}


def _current_term(conn: Connection, as_of: date) -> tuple[int, date] | None:
    """The term running on `as_of` (the latest start if terms overlap)."""
    row = conn.execute(
        text(
            "SELECT id, start_date FROM core.terms WHERE start_date <= :d AND end_date >= :d "
            "ORDER BY start_date DESC, id DESC LIMIT 1"
        ),
        {"d": as_of},
    ).one_or_none()
    return None if row is None else (int(row[0]), row[1])


def _term_students(conn: Connection, term_id: int) -> list[int]:
    found = conn.execute(
        text(
            "SELECT DISTINCT e.student_id FROM core.enrollments e "
            "JOIN core.courses c ON c.id = e.course_id WHERE c.term_id = :t ORDER BY 1"
        ),
        {"t": term_id},
    )
    return [int(s) for s in found.scalars()]


def run_pipeline(
    engine: Engine,
    csv_dir: Path,
    registry: Registry,
    as_of: date,
    cfg: CaseConfig | None = None,
) -> NightSummary:
    with engine.begin() as conn:
        _, report = ingest(conn, read_csv_dir(csv_dir), as_of, source=f"csv:{csv_dir.name}")
    if report.status == "fail":
        raise DataQualityFailed(f"data quality failed on {as_of}; see raw.dq_reports")

    with engine.connect() as conn:
        term = _current_term(conn, as_of)
        student_ids = [] if term is None else _term_students(conn, term[0])
        tables = load_core_tables(conn, as_of) if student_ids else None

    week: int | None = None
    scored: list[Score] = []
    features = pd.DataFrame()
    model: CalibratedModel | None = None
    if term is not None and tables is not None:
        week, model = load_production_model(registry, target_week(term[1], as_of))
        features, scored = score_students(tables, student_ids, as_of, model)
    skipped = None if scored else ("no active term" if term is None else "no enrolled students")

    with engine.begin() as conn:
        plan = run_night(conn, scored, as_of, cfg)
        reasons = 0
        if model is not None and scored:
            by_student = _open_cases(conn, [s.student_id for s in scored])
            rows = reason_rows(model, features, by_student, as_of)
            _store_reasons(conn, rows, list(by_student.values()), as_of)
            reasons = len(rows)
        timers = run_timers(conn, as_of, cfg)

    summary = NightSummary(
        as_of=as_of.isoformat(),
        data_quality=report.status,
        skipped=skipped,
        model_week=week,
        scored=len(scored),
        opened=len(plan.opened),
        deferred=len(plan.deferred),
        unassigned=len(plan.unassigned),
        reasons=reasons,
        moved_to_review=len(timers.moved_to_review),
        newly_overdue=len(timers.newly_overdue),
    )
    log.info("nightly run finished: %s", asdict(summary))
    return summary


def run_nightly(as_of: str | None = None) -> dict[str, object]:
    """Celery entry point. `as_of` (ISO date) is for manual re-runs; default is today."""
    settings = get_settings()
    if not settings.database_url or not settings.csv_dir:
        raise RuntimeError("DATABASE_URL and CSV_DIR must be set for the nightly run")
    day = (
        date.fromisoformat(as_of) if as_of else datetime.now(ZoneInfo(settings.app_timezone)).date()
    )
    engine = create_engine(settings.database_url)
    try:
        summary = run_pipeline(
            engine, Path(settings.csv_dir), Registry(Path(settings.model_store)), day
        )
    finally:
        engine.dispose()
    return asdict(summary)


run_nightly = app.task(name=NIGHTLY_TASK)(run_nightly)
