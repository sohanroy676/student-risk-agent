"""Train the weekly models on OULAD, check them with the promotion gate, register in MLflow.

    python -m app.ml.release --oulad path/to/oulad --store mlruns

Always logs the new versions and a model card. The `production` alias moves only if the gate
passes. To accept specific blocks, give a named sign-off that lists them:

    --sign-off-name "A. Dean" --sign-off-reason "pilot only" --cover gap_high:region

The recall gaps are measured at week 4 with the top 20% flagged (a placeholder rule).
"""

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from app.ingest.oulad import OuladData, load_oulad
from app.ml.baseline import PRODUCTION, WEEKS
from app.ml.calibrate import CalibratedModel, evaluate_calibrated, fit_week
from app.ml.card import render_card
from app.ml.fairness import FLAG_FRACTION, PROTECTED, fairness_report
from app.ml.gate import Metrics, SignOff, check
from app.ml.registry import GATE_WEEK, Registry
from app.ml.report import oulad_cohort


def build_release(
    data: OuladData, test_year: int, flag_fraction: float
) -> tuple[dict[int, CalibratedModel], Metrics, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fitted models by week, gate metrics, the weekly table, recall gaps and group table."""
    tables, cohort = data.to_core_tables(), oulad_cohort(data, test_year)
    weekly = evaluate_calibrated(tables, cohort, WEEKS)
    fitted = {}
    tests = {}
    for week in WEEKS:
        fitted[week], features, y = fit_week(tables, cohort, week)
        tests[week] = (features, y)
    features, y_test = tests[GATE_WEEK]
    score = pd.Series(fitted[GATE_WEEK].raw_score(features), index=features.index)
    attributes = data.attributes.set_index("student_id").loc[score.index, list(PROTECTED)]
    groups, gaps = fairness_report(attributes, y_test, score, flag_fraction)
    row = weekly[weekly["week"] == GATE_WEEK].iloc[0]
    metrics = Metrics(
        auc_week4=float(row["auc_cal"]),
        ece=float(row["ece"]),
        recall_gaps=dict(zip(gaps["attribute"], gaps["recall_gap"].astype(float), strict=True)),
    )
    return fitted, metrics, weekly, gaps, groups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--oulad", type=Path, required=True, help="folder with the OULAD CSVs")
    parser.add_argument("--store", type=Path, default=Path("mlruns"), help="MLflow store folder")
    parser.add_argument("--test-year", type=int, default=2014)
    parser.add_argument("--flag-fraction", type=float, default=FLAG_FRACTION)
    parser.add_argument("--sign-off-name", default="")
    parser.add_argument("--sign-off-reason", default="")
    parser.add_argument("--cover", action="append", default=[], help="block code to accept")
    args = parser.parse_args()

    sign_off = None
    if args.sign_off_name or args.sign_off_reason or args.cover:
        sign_off = SignOff(args.sign_off_name, args.sign_off_reason, frozenset(args.cover))

    data = load_oulad(args.oulad)
    fitted, metrics, weekly, gaps, groups = build_release(data, args.test_year, args.flag_fraction)
    registry = Registry(args.store)
    preview = check(metrics, registry.current_metrics(), sign_off)
    card = render_card(
        model_name=f"calibrated {PRODUCTION}",
        generated_on=date.today(),
        trained_on=f"presentations before {args.test_year}",
        tested_on=f"presentations in {args.test_year}",
        weekly=weekly.drop(columns=["ece_ok", "lift_ok"]),
        gaps=gaps,
        groups=groups,
        flag_fraction=args.flag_fraction,
        result=preview,
        sign_off=sign_off,
    )
    params = {"model": PRODUCTION, "test_year": args.test_year, "flag_fraction": args.flag_fraction}
    versions = registry.log_release(fitted, metrics, params, card)
    result = registry.promote(versions, metrics, sign_off)

    print(card)
    print(f"registered versions: {versions}")
    print(
        "PROMOTED"
        if result.passed
        else "BLOCKED: " + ", ".join(result.blocks + result.hard_failures)
    )


if __name__ == "__main__":
    main()
