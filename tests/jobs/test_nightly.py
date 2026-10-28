"""Pure parts of the nightly run (no database): week choice, scoring, reasons."""

import time
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pandas as pd
import pytest

from app.features.snapshot import FEATURE_NAMES
from app.features.tables import CoreTables
from app.jobs import nightly
from app.jobs.nightly import (
    load_production_model,
    reason_rows,
    score_students,
    target_week,
)
from app.ml.calibrate import CalibratedModel
from app.ml.registry import NoProductionModel
from data.synthetic import generator
from data.synthetic.frames import to_core_tables

AS_OF = generator.TERM_START + timedelta(weeks=8, days=2)
IDS = list(range(1, generator.N_STUDENTS + 1))


class FakeRegistry:
    def __init__(self, available: dict[int, Any]) -> None:
        self.available = available
        self.asked: list[int] = []

    def load_production(self, week: int) -> Any:
        self.asked.append(week)
        if week not in self.available:
            raise NoProductionModel(f"no model for week {week}")
        return self.available[week]


@pytest.mark.parametrize(
    ("days", "week"), [(0, 0), (6, 0), (7, 1), (13, 1), (14, 2), (56, 8), (60, 8), (104, 14)]
)
def test_target_week_counts_whole_weeks_since_the_term_start(days: int, week: int) -> None:
    start = date(2026, 1, 5)
    assert target_week(start, start + timedelta(days=days)) == week


@pytest.mark.parametrize(
    ("target", "picked"), [(0, 1), (1, 1), (3, 2), (5, 4), (7, 6), (8, 8), (14, 8)]
)
def test_the_latest_trained_week_at_or_before_the_target_is_used(target: int, picked: int) -> None:
    registry = FakeRegistry({w: f"model{w}" for w in (1, 2, 4, 6, 8)})
    assert load_production_model(registry, target) == (picked, f"model{picked}")  # type: ignore[arg-type]


def test_a_missing_week_falls_back_to_an_earlier_model() -> None:
    registry = FakeRegistry({1: "m1", 4: "m4"})
    assert load_production_model(registry, 8) == (4, "m4")  # type: ignore[arg-type]
    assert registry.asked == [8, 6, 4]


def test_no_production_model_at_all_is_an_error_not_a_silent_skip() -> None:
    with pytest.raises(NoProductionModel):
        load_production_model(FakeRegistry({}), 8)  # type: ignore[arg-type]


def test_scores_are_probabilities_one_per_student_in_model_column_order(
    tables: CoreTables, model: CalibratedModel
) -> None:
    features, scores = score_students(tables, IDS, AS_OF, model)
    assert list(features.columns) == list(FEATURE_NAMES)
    assert [s.student_id for s in scores] == IDS
    assert all(0.0 <= s.probability <= 1.0 for s in scores)
    assert len({round(s.probability, 6) for s in scores}) > 1


def test_no_students_means_no_scores_and_no_model_call(
    tables: CoreTables, model: CalibratedModel
) -> None:
    features, scores = score_students(tables, [], AS_OF, model)
    assert features.empty and scores == []


def test_facts_dated_after_as_of_cannot_change_a_score(
    tables: CoreTables, model: CalibratedModel
) -> None:
    """Add a week of tomorrow's worst-case facts; tonight's scores must not move."""
    later = pd.Timestamp(AS_OF + timedelta(days=1))
    extra_att = tables.attendance.copy()
    extra_att["class_date"] = later
    extra_att["present"] = False
    extra_events = tables.lms_events.copy()
    extra_events["occurred_at"] = later + pd.Timedelta(hours=3)
    extra_marks = tables.marks.copy()
    extra_marks["submitted_on"] = later
    extra_marks["marks_obtained"] = 0.0
    changed = replace(
        tables,
        attendance=pd.concat([tables.attendance, extra_att], ignore_index=True),
        lms_events=pd.concat([tables.lms_events, extra_events], ignore_index=True),
        marks=pd.concat([tables.marks, extra_marks], ignore_index=True),
    )
    _, before = score_students(tables, IDS, AS_OF, model)
    _, after = score_students(changed, IDS, AS_OF, model)
    assert before == after


def test_no_protected_attribute_reaches_the_model(model: CalibratedModel) -> None:
    banned = {"gender", "category", "caste", "religion", "disability", "region", "age", "income"}
    columns = {c.lower() for c in model.model.booster_.feature_name()}
    assert columns == {c.lower() for c in FEATURE_NAMES}
    assert not any(b in c for c in columns for b in banned)


def test_reasons_are_labelled_by_case_not_student_and_capped_at_three(
    tables: CoreTables, model: CalibratedModel
) -> None:
    features, scores = score_students(tables, IDS, AS_OF, model)
    worst = [s.student_id for s in sorted(scores, key=lambda s: -s.probability)[:10]]
    cases = {student: 1000 + i for i, student in enumerate(worst)}
    rows = reason_rows(model, features, cases, AS_OF)
    assert rows
    assert {r["case_id"] for r in rows} <= set(cases.values())
    for row in rows:
        assert str(row["fact_id"]).startswith(f"case-{row['case_id']}/")
        assert str(row["fact_id"]).endswith(f"/{AS_OF.isoformat()}")
        assert row["rank"] in (1, 2, 3)
    per_case = pd.Series([r["case_id"] for r in rows]).value_counts()
    assert per_case.max() <= 3
    student_refs = {f"/{s}/" for s in worst}
    assert not any(any(ref in str(r["fact_id"]) for ref in student_refs) for r in rows)


def test_reasons_skip_students_without_a_feature_row(
    tables: CoreTables, model: CalibratedModel
) -> None:
    features, _ = score_students(tables, IDS[:5], AS_OF, model)
    assert reason_rows(model, features, {999_999: 1}, AS_OF) == []
    assert reason_rows(model, features, {}, AS_OF) == []


def test_the_task_is_registered_under_the_scheduled_name() -> None:
    from app.jobs import NIGHTLY_TASK
    from app.jobs import app as celery_app

    assert nightly.run_nightly.name == NIGHTLY_TASK
    assert NIGHTLY_TASK in celery_app.tasks


def test_the_task_refuses_to_run_without_database_and_csv_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CSV_DIR", raising=False)
    with pytest.raises(RuntimeError, match="CSV_DIR"):
        nightly.run_nightly()


def test_scoring_five_thousand_students_takes_seconds_not_minutes(model: CalibratedModel) -> None:
    """The snapshot and scoring leg of the 30-minute budget; the database legs run in CI."""
    big = to_core_tables(generator.generate(seed=1, n_students=5000))
    started = time.perf_counter()
    _, scores = score_students(big, list(range(1, 5001)), AS_OF, model)
    elapsed = time.perf_counter() - started
    assert len(scores) == 5000
    assert elapsed < 120, f"snapshot + scoring took {elapsed:.0f} s"
