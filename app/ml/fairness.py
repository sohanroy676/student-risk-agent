"""Fairness audit of the production model on the protected attributes, evaluation only.

    python -m app.ml.fairness --oulad path/to/oulad --out docs/fairness

The attributes come from `OuladData.attributes`, a frame that never reaches `build_snapshot`,
so they cannot be model features; this module takes finished scores and attributes, never a
model. A student is flagged when their score is in the top `flag_fraction` of the whole test
cohort (one cut-off for everyone), and recall, selection rate and precision are compared by
group. The flag fraction is a placeholder until the band cut-offs are set in v0.4.
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

from app.ingest.oulad import load_oulad
from app.ml.calibrate import fit_week
from app.ml.report import oulad_cohort

PROTECTED = ("gender", "region", "highest_education", "imd_band", "age_band", "disability")
FLAG_FRACTION = 0.20
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


def fairness_report(
    attributes: pd.DataFrame,
    y: pd.Series,
    score: pd.Series,
    flag_fraction: float = FLAG_FRACTION,
    min_group_size: int = MIN_GROUP_SIZE,
    min_positives: int = MIN_POSITIVES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per-group table, per-attribute recall gaps) for finished scores on the test cohort."""
    flagged = flag_top(score, flag_fraction)
    table = group_table(attributes, y, flagged, min_group_size, min_positives)
    return table, recall_gaps(table)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--oulad", type=Path, required=True, help="folder with the OULAD CSVs")
    parser.add_argument("--out", type=Path, default=Path("docs/fairness"))
    parser.add_argument("--test-year", type=int, default=2014)
    parser.add_argument("--week", type=int, default=GATE_WEEK)
    parser.add_argument("--flag-fraction", type=float, default=FLAG_FRACTION)
    args = parser.parse_args()

    data = load_oulad(args.oulad)
    cohort = oulad_cohort(data, args.test_year)
    fitted, test_features, y_test = fit_week(data.to_core_tables(), cohort, args.week)
    score = pd.Series(fitted.raw_score(test_features), index=test_features.index)
    attributes = data.attributes.set_index("student_id").loc[score.index, list(PROTECTED)]
    table, gaps = fairness_report(attributes, y_test, score, args.flag_fraction)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out.with_name(args.out.name + "_groups.csv"), index=False)
    gaps.to_csv(args.out.with_name(args.out.name + "_gaps.csv"), index=False)
    print(f"week {args.week}, flagging the top {args.flag_fraction:.0%} by score\n")
    print(gaps.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
