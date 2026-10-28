"""Fairness audit of the production model on the protected attributes, evaluation only.

    python -m app.ml.fairness --oulad path/to/oulad --out docs/fairness

The attributes come from `OuladData.attributes`, a frame that never reaches `build_snapshot`,
so they cannot be model features; this module takes finished scores and attributes, never a
model. By default a student is flagged when their calibrated probability reaches the red-band
cut-off of the case engine (`CaseConfig.red_enter`; one cut-off for everyone), which is who
becomes a case. This leaves out hysteresis and the per-mentor nightly cap. With `--flag-fraction`
the top share of the test cohort by raw score is flagged instead (the old placeholder rule).
Recall, selection rate and precision are compared by group.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from fairlearn.metrics import (
    MetricFrame,
    false_positive_rate,
    selection_rate,
    true_positive_rate,
)
from sklearn.metrics import precision_score

from app.cases.config import CaseConfig
from app.ingest.oulad import load_oulad
from app.ml.calibrate import CalibratedModel, fit_week
from app.ml.report import oulad_cohort

PROTECTED = ("gender", "region", "highest_education", "imd_band", "age_band", "disability")
FLAG_FRACTION = 0.20  # only for the top-share rule
RED_CUTOFF = CaseConfig().red_enter
RECALL_GAP_LIMIT = 0.10
MIN_GROUP_SIZE = 100
MIN_POSITIVES = 20
GATE_WEEK = 4
TABLE_COLUMNS = [
    "attribute",
    "group",
    "n",
    "positives",
    "at_risk_rate",
    "selection_rate",
    "recall",
    "precision",
    "false_positive_rate",
    "reliable",
]


def flag_top(score: pd.Series, frac: float = FLAG_FRACTION) -> pd.Series:
    """True for the top `frac` of rows by score; ties at the cut-off are all flagged."""
    if not 0 < frac <= 1:
        raise ValueError("frac must be in (0, 1]")
    if score.empty or score.isna().any():
        raise ValueError("score must be non-empty and free of NaN")
    k = max(1, int(np.ceil(frac * len(score))))
    cutoff = score.sort_values(ascending=False).iloc[k - 1]
    return pd.Series(score >= cutoff, index=score.index)


def flag_at(probability: pd.Series, cutoff: float = RED_CUTOFF) -> pd.Series:
    """True where the calibrated probability reaches `cutoff` (the red band's entry point)."""
    if not 0 < cutoff <= 1:
        raise ValueError("cutoff must be in (0, 1]")
    if probability.empty or probability.isna().any():
        raise ValueError("probability must be non-empty and free of NaN")
    return pd.Series(probability >= cutoff, index=probability.index)


def choose_flags(
    model: CalibratedModel,
    features: pd.DataFrame,
    flag_fraction: float | None = None,
    cutoff: float = RED_CUTOFF,
) -> tuple[pd.Series, str]:
    """(who is flagged, a sentence saying how). No `flag_fraction` means the red band."""
    if flag_fraction is not None:
        raw = pd.Series(model.raw_score(features), index=features.index)
        flagged, rule = flag_top(raw, flag_fraction), f"top {flag_fraction:.0%} by score"
    else:
        probability = pd.Series(model.predict_proba(features), index=features.index)
        flagged = flag_at(probability, cutoff)
        rule = f"red band (probability at least {cutoff:.2f})"
    return flagged, f"{rule}; {flagged.mean():.0%} of the test cohort flagged"


def _precision(y_true: pd.Series, y_pred: pd.Series) -> float:
    return float(precision_score(y_true, y_pred, zero_division=np.nan))


def group_table(
    attributes: pd.DataFrame,
    y: pd.Series,
    flagged: pd.Series,
    min_group_size: int = MIN_GROUP_SIZE,
    min_positives: int = MIN_POSITIVES,
) -> pd.DataFrame:
    """One row per (attribute, group). Groups too small to judge are listed but `reliable=False`.

    `attributes` has one row per student, indexed like `y` and `flagged`; missing values
    become their own group "unknown". Recall is NaN for a group with no positives (Fairlearn
    reports 0.0 there, which would read as a perfect miss).
    """
    if not (attributes.index.equals(y.index) and y.index.equals(flagged.index)):
        raise ValueError("attributes, y and flagged must share the same index")
    unknown = [c for c in attributes.columns if c not in PROTECTED]
    if unknown:
        raise ValueError(f"not protected attributes this audit knows: {unknown}")
    truth, pred = y.astype(int), flagged.astype(int)
    metrics = {
        "n": lambda yt, yp: len(yt),
        "positives": lambda yt, yp: int(yt.sum()),
        "at_risk_rate": lambda yt, yp: float(yt.mean()),
        "selection_rate": selection_rate,
        "recall": true_positive_rate,
        "precision": _precision,
        "false_positive_rate": false_positive_rate,
    }
    parts = []
    for name in attributes.columns:
        groups = attributes[name].astype("string").fillna("unknown")
        frame = MetricFrame(metrics=metrics, y_true=truth, y_pred=pred, sensitive_features=groups)
        part = frame.by_group.reset_index()
        part.columns = ["group", *frame.by_group.columns]
        part.insert(0, "attribute", name)
        parts.append(part)
    table = pd.concat(parts, ignore_index=True)
    table[["n", "positives"]] = table[["n", "positives"]].astype(int)
    table.loc[table["positives"] == 0, "recall"] = np.nan
    table["reliable"] = (table["n"] >= min_group_size) & (table["positives"] >= min_positives)
    return pd.DataFrame(table[TABLE_COLUMNS])


def recall_gaps(table: pd.DataFrame, limit: float = RECALL_GAP_LIMIT) -> pd.DataFrame:
    """Largest recall difference between reliable groups, per attribute.

    With fewer than two reliable groups the gap is NaN, `assessed` is False and `within_limit`
    is False: an attribute that could not be checked must not pass a gate by default.
    """
    rows = []
    for attribute, part in table[table["reliable"]].groupby("attribute", sort=False):
        recall = part.set_index("group")["recall"]
        gap = float(recall.max() - recall.min()) if len(recall) >= 2 else float("nan")
        rows.append(
            {
                "attribute": attribute,
                "reliable_groups": len(recall),
                "recall_gap": gap,
                "lowest_recall_group": recall.idxmin(),
                "highest_recall_group": recall.idxmax(),
                "assessed": len(recall) >= 2,
                "within_limit": bool(gap <= limit),  # False when not assessed (NaN gap)
            }
        )
    seen = {r["attribute"] for r in rows}
    for attribute in table["attribute"].unique():
        if attribute not in seen:  # no group big enough to compare
            rows.append(
                {
                    "attribute": attribute,
                    "reliable_groups": 0,
                    "recall_gap": float("nan"),
                    "lowest_recall_group": None,
                    "highest_recall_group": None,
                    "assessed": False,
                    "within_limit": False,
                }
            )
    return pd.DataFrame(rows)


def fairness_from_flags(
    attributes: pd.DataFrame,
    y: pd.Series,
    flagged: pd.Series,
    min_group_size: int = MIN_GROUP_SIZE,
    min_positives: int = MIN_POSITIVES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per-group table, per-attribute recall gaps) for a given set of flagged students."""
    table = group_table(attributes, y, flagged, min_group_size, min_positives)
    return table, recall_gaps(table)


def fairness_report(
    attributes: pd.DataFrame,
    y: pd.Series,
    score: pd.Series,
    flag_fraction: float = FLAG_FRACTION,
    min_group_size: int = MIN_GROUP_SIZE,
    min_positives: int = MIN_POSITIVES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Like `fairness_from_flags`, flagging the top `flag_fraction` of `score`."""
    flagged = flag_top(score, flag_fraction)
    return fairness_from_flags(attributes, y, flagged, min_group_size, min_positives)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--oulad", type=Path, required=True, help="folder with the OULAD CSVs")
    parser.add_argument("--out", type=Path, default=Path("docs/fairness"))
    parser.add_argument("--test-year", type=int, default=2014)
    parser.add_argument("--week", type=int, default=GATE_WEEK)
    parser.add_argument(
        "--flag-fraction",
        type=float,
        default=None,
        help="flag this top share by raw score instead of the red band",
    )
    parser.add_argument("--red-cutoff", type=float, default=RED_CUTOFF)
    args = parser.parse_args()

    data = load_oulad(args.oulad)
    cohort = oulad_cohort(data, args.test_year)
    fitted, test_features, y_test = fit_week(data.to_core_tables(), cohort, args.week)
    flagged, rule = choose_flags(fitted, test_features, args.flag_fraction, args.red_cutoff)
    attributes = data.attributes.set_index("student_id").loc[flagged.index, list(PROTECTED)]
    table, gaps = fairness_from_flags(attributes, y_test, flagged)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out.with_name(args.out.name + "_groups.csv"), index=False)
    gaps.to_csv(args.out.with_name(args.out.name + "_gaps.csv"), index=False)
    print(f"week {args.week}, flagging: {rule}\n")
    print(gaps.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
