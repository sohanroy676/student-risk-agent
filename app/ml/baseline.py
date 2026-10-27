"""Logistic-regression baseline, evaluated week by week.

For each week N the feature snapshot is taken at `term_start + 7N days`, a fresh model is
fitted on the training cohort and scored on the test cohort. The rule-based score is
evaluated on the same test rows, so the table shows what the model adds over the rules.
Only students still registered at `as_of` are used: someone who already left is not an
early-warning case. Features come from `build_snapshot` alone, so protected attributes
cannot enter the model.

The cohort frame is indexed by `student_id` with columns:
`term_start` (datetime), `at_risk` (bool), `split` ("train"/"test") and
`unregistered_on` (datetime, NaT if the student never left).
"""

from collections.abc import Sequence

import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from app.features.snapshot import build_snapshot
from app.features.tables import CoreTables
from app.ml.rules import rule_score

WEEKS = (1, 2, 4, 6, 8)
COHORT_COLUMNS = {"term_start", "at_risk", "split", "unregistered_on"}


def check_cohort(cohort: pd.DataFrame) -> None:
    missing = COHORT_COLUMNS - set(cohort.columns)
    if missing:
        raise ValueError(f"cohort is missing columns: {sorted(missing)}")
    if not cohort.index.is_unique:
        raise ValueError("cohort has duplicate student ids")
    bad = set(cohort["split"].unique()) - {"train", "test"}
    if bad:
        raise ValueError(f"cohort split must be 'train' or 'test', got {sorted(bad)}")


def weekly_matrix(
    tables: CoreTables, cohort: pd.DataFrame, week: int
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Features, labels and split for students still registered `week` weeks into their term."""
    check_cohort(cohort)
    parts = []
    for start, group in cohort.groupby("term_start"):
        as_of = pd.Timestamp(start) + pd.Timedelta(days=7 * week)  # type: ignore[arg-type]
        left = group["unregistered_on"].notna() & (group["unregistered_on"] <= as_of)
        active = group[~left]
        if not active.empty:
            parts.append(build_snapshot(tables, active.index, as_of.date()))
    if not parts:
        raise ValueError(f"no registered students in the cohort at week {week}")
    features = pd.concat(parts)
    return features, cohort.loc[features.index, "at_risk"], cohort.loc[features.index, "split"]


def make_model() -> Pipeline:
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(max_iter=1000),
    )


def _auc(y: pd.Series, score: pd.Series | pd.api.extensions.ExtensionArray) -> float:
    if y.nunique() < 2:
        return float("nan")
    return float(roc_auc_score(y, score))


def evaluate_by_week(
    tables: CoreTables, cohort: pd.DataFrame, weeks: Sequence[int] = WEEKS
) -> pd.DataFrame:
    """One row per week: sizes, test positive rate and test AUC for the model and the rules."""
    rows = []
    for week in weeks:
        features, y, split = weekly_matrix(tables, cohort, week)
        train, test = split == "train", split == "test"
        auc_model = float("nan")
        if y[train].nunique() == 2 and y[test].nunique() == 2:
            model = make_model().fit(features[train], y[train])
            auc_model = _auc(y[test], model.predict_proba(features[test])[:, 1])
        rows.append(
            {
                "week": week,
                "n_train": int(train.sum()),
                "n_test": int(test.sum()),
                "test_at_risk_rate": float(y[test].mean()) if test.any() else float("nan"),
                "auc_logreg": auc_model,
                "auc_rules": _auc(y[test], rule_score(features[test]))
                if test.any()
                else float("nan"),
            }
        )
    return pd.DataFrame(rows)
