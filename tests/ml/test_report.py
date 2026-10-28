import sys
from pathlib import Path

import pandas as pd
import pytest

from app.ingest.oulad import load_oulad
from app.ml import report


def test_cohort_splits_train_and_test_by_presentation_year(oulad_dir: Path) -> None:
    cohort = report.oulad_cohort(load_oulad(oulad_dir), test_year=2014)
    by_year = cohort.groupby(cohort["term_start"].dt.year)["split"].agg(set)
    assert by_year.loc[2013] == {"train"}
    assert by_year.loc[2014] == {"test"}
    assert set(cohort.columns) == {"term_start", "at_risk", "unregistered_on", "split"}


def test_plot_handles_missing_aucs(tmp_path: Path) -> None:
    results = pd.DataFrame(
        {"week": [1, 8], "auc_logreg": [0.7, float("nan")], "auc_rules": [0.6, 0.8]}
    )
    out = tmp_path / "chart.png"
    report.plot_auc_by_week(results, out)
    assert out.stat().st_size > 1000


def test_cli_writes_csv_and_png(
    oulad_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "nested" / "baseline"
    monkeypatch.setattr(sys, "argv", ["report", "--oulad", str(oulad_dir), "--out", str(out)])
    report.main()
    table = pd.read_csv(out.with_suffix(".csv"))
    assert table["week"].tolist() == [1, 2, 4, 6, 8]
    assert out.with_suffix(".png").is_file()
    assert "auc_logreg" in capsys.readouterr().out


def test_cli_fails_clearly_on_a_missing_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["report", "--oulad", str(tmp_path / "nope")])
    with pytest.raises(ValueError, match="missing"):
        report.main()


def test_cli_reports_both_models_by_default_and_one_on_request(
    oulad_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    both = tmp_path / "both"
    monkeypatch.setattr(sys, "argv", ["report", "--oulad", str(oulad_dir), "--out", str(both)])
    report.main()
    assert {"auc_logreg", "auc_lgbm"} <= set(pd.read_csv(both.with_suffix(".csv")).columns)

    only = tmp_path / "only"
    argv = ["report", "--oulad", str(oulad_dir), "--out", str(only), "--model", "lgbm"]
    monkeypatch.setattr(sys, "argv", argv)
    report.main()
    columns = set(pd.read_csv(only.with_suffix(".csv")).columns)
    assert "auc_lgbm" in columns
    assert "auc_logreg" not in columns


def test_cli_rejects_an_unknown_model(
    oulad_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["report", "--oulad", str(oulad_dir), "--out", str(tmp_path / "x"), "--model", "xgb"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        report.main()


def test_plot_draws_lightgbm_when_present(tmp_path: Path) -> None:
    results = pd.DataFrame(
        {"week": [1, 8], "auc_lgbm": [0.7, 0.8], "auc_rules": [0.6, 0.8]}
    )  # no auc_logreg column
    out = tmp_path / "chart.png"
    report.plot_auc_by_week(results, out)
    assert out.stat().st_size > 1000
