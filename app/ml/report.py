"""Evaluate the baseline on OULAD and chart AUC by week against the blueprint targets.

    python -m app.ml.report --oulad path/to/oulad --out docs/baseline

Writes `<out>.csv` and `<out>.png`. Train on presentations before `--test-year`, test on
that year (default: 2013 train, 2014 test).
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from app.ingest.oulad import OuladData, load_oulad  # noqa: E402
from app.ml.baseline import MODELS, evaluate_by_week  # noqa: E402

TARGETS = {1: 0.72, 8: 0.86}
MODEL_LABELS = {"auc_logreg": "Logistic regression", "auc_lgbm": "LightGBM"}


def oulad_cohort(data: OuladData, test_year: int = 2014) -> pd.DataFrame:
    labels = data.labels.set_index("student_id")
    cohort = labels[["term_start", "at_risk", "unregistered_on"]].copy()
    cohort["split"] = (cohort["term_start"].dt.year >= test_year).map(
        {True: "test", False: "train"}
    )
    return cohort


def plot_auc_by_week(results: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for column, label in MODEL_LABELS.items():
        if column in results.columns:
            ax.plot(results["week"], results[column], marker="o", label=label)
    ax.plot(results["week"], results["auc_rules"], marker="s", linestyle="--", label="Rule score")
    ax.scatter(list(TARGETS), list(TARGETS.values()), marker="*", s=160, color="black",
               zorder=3, label="Blueprint target")  # fmt: skip
    ax.set_xlabel("Week of term")
    ax.set_ylabel("Test AUC")
    ax.set_ylim(0.5, 1.0)
    ax.set_xticks(results["week"])
    ax.grid(alpha=0.3)
    ax.legend()
    ax.set_title("OULAD baseline: AUC by week")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--oulad", type=Path, required=True, help="folder with the OULAD CSVs")
    parser.add_argument("--out", type=Path, default=Path("docs/baseline"))
    parser.add_argument("--test-year", type=int, default=2014)
    parser.add_argument("--model", choices=[*MODELS, "both"], default="both")
    args = parser.parse_args()

    data = load_oulad(args.oulad)
    models = list(MODELS) if args.model == "both" else [args.model]
    results = evaluate_by_week(
        data.to_core_tables(), oulad_cohort(data, args.test_year), models=models
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.out.with_suffix(".csv"), index=False)
    plot_auc_by_week(results, args.out.with_suffix(".png"))
    print(results.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
