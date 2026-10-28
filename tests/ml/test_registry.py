import json
import sys
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest

from app.ml import release
from app.ml.calibrate import CalibratedModel, fit_calibrated
from app.ml.gate import Metrics, SignOff
from app.ml.registry import (
    ALIAS,
    Registry,
    metrics_from_json,
    metrics_to_json,
    model_name,
)

GOOD = Metrics(0.74, 0.02, {"gender": 0.03, "region": 0.04})
WEEKS = (4, 8)


@pytest.fixture(scope="module")
def fitted() -> dict[int, CalibratedModel]:
    rng = np.random.default_rng(0)
    n = 600
    x = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = pd.Series(rng.random(n) < 1 / (1 + np.exp(-2 * x["a"])))
    starts = pd.Series(
        pd.to_datetime(np.where(np.arange(n) < n // 2, "2013-02-01", "2013-10-01")), index=x.index
    )
    model = fit_calibrated(x, y, starts)
    return dict.fromkeys(WEEKS, model)


def release_of(
    registry: Registry,
    fitted: dict[int, CalibratedModel],
    metrics: Metrics,
    sign_off: SignOff | None = None,
) -> tuple[dict[int, str], bool]:
    versions = registry.log_release(fitted, metrics, {"model": "lgbm"}, "# card")
    return versions, registry.promote(versions, metrics, sign_off).passed


def alias_version(registry: Registry, week: int) -> str:
    return str(registry.client.get_model_version_by_alias(model_name(week), ALIAS).version)


def test_metrics_survive_a_json_round_trip_including_nan() -> None:
    metrics = Metrics(0.7, float("nan"), {"gender": 0.1, "region": float("nan")})
    back = metrics_from_json(metrics_to_json(metrics))
    assert back.auc_week4 == 0.7 and np.isnan(back.ece)
    assert back.recall_gaps["gender"] == 0.1 and np.isnan(back.recall_gaps["region"])


def test_first_release_is_promoted_and_the_model_reloads(
    tmp_path: Path, fitted: dict[int, CalibratedModel]
) -> None:
    registry = Registry(tmp_path)
    assert registry.current_metrics() is None
    versions, passed = release_of(registry, fitted, GOOD)
    assert passed
    assert all(alias_version(registry, w) == versions[w] for w in WEEKS)
    assert registry.current_metrics() == GOOD
    loaded = mlflow.sklearn.load_model(f"models:/{model_name(4)}@{ALIAS}")
    probe = pd.DataFrame({"a": [-1.0, 0.0, 1.0], "b": [0.0, 0.0, 0.0]})
    np.testing.assert_array_equal(loaded.predict_proba(probe), fitted[4].predict_proba(probe))


def test_a_worse_candidate_is_logged_but_does_not_replace_production(
    tmp_path: Path, fitted: dict[int, CalibratedModel]
) -> None:
    registry = Registry(tmp_path)
    first, _ = release_of(registry, fitted, GOOD)
    worse, passed = release_of(registry, fitted, Metrics(0.70, 0.02, GOOD.recall_gaps))
    assert not passed and worse[4] != first[4]
    assert alias_version(registry, 4) == first[4]
    tag = registry.client.get_model_version(model_name(4), worse[4]).tags["gate_result"]
    assert json.loads(tag)["blocks"] == ["auc_lower"]


def test_sign_off_promotes_a_blocked_candidate_and_is_recorded(
    tmp_path: Path, fitted: dict[int, CalibratedModel]
) -> None:
    registry = Registry(tmp_path)
    gappy = Metrics(0.74, 0.02, {"gender": 0.03, "region": 0.2})
    versions, passed = release_of(registry, fitted, gappy)
    assert not passed and registry.current_metrics() is None
    sign = SignOff("A. Dean", "pilot only", frozenset({"gap_high:region"}))
    versions, passed = release_of(registry, fitted, gappy, sign)
    assert passed and alias_version(registry, 4) == versions[4]
    tags = registry.client.get_model_version(model_name(4), versions[4]).tags
    assert json.loads(tags["sign_off"]) == {"name": "A. Dean", "reason": "pilot only"}


def test_missing_metrics_stay_blocked_whatever_the_sign_off(
    tmp_path: Path, fitted: dict[int, CalibratedModel]
) -> None:
    registry = Registry(tmp_path)
    unassessed = Metrics(0.74, 0.02, {"gender": float("nan")})
    sign = SignOff("A. Dean", "please", frozenset({"gap_high:gender", "unassessed:gender"}))
    _, passed = release_of(registry, fitted, unassessed, sign)
    assert not passed and registry.current_metrics() is None


def test_a_release_without_the_gate_week_is_refused(
    tmp_path: Path, fitted: dict[int, CalibratedModel]
) -> None:
    with pytest.raises(ValueError, match="week-4"):
        Registry(tmp_path).log_release({8: fitted[8]}, GOOD, {}, "")


def test_a_production_model_without_recorded_metrics_stops_the_gate(
    tmp_path: Path, fitted: dict[int, CalibratedModel]
) -> None:
    registry = Registry(tmp_path)
    versions, _ = release_of(registry, fitted, GOOD)
    registry.client.delete_model_version_tag(model_name(4), versions[4], "gate_metrics")
    with pytest.raises(ValueError, match="no recorded metrics"):
        registry.current_metrics()


def test_the_store_can_be_reopened(tmp_path: Path, fitted: dict[int, CalibratedModel]) -> None:
    versions, _ = release_of(Registry(tmp_path), fitted, GOOD)
    assert alias_version(Registry(tmp_path), 4) == versions[4]


def test_release_cli_fails_clearly_with_one_training_presentation(
    oulad_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["release", "--oulad", str(oulad_dir), "--store", str(tmp_path / "store")]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(ValueError, match="two training presentations"):
        release.main()


def test_release_cli_refuses_an_incomplete_sign_off(
    oulad_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["release", "--oulad", str(oulad_dir), "--sign-off-name", "A. Dean"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(ValueError, match="name and a reason"):
        release.main()
