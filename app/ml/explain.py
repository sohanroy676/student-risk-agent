"""Per-student SHAP contributions from the production LightGBM and the top reasons built on them.

LightGBM's `pred_contrib=True` returns exact TreeSHAP values (the same algorithm as
`shap.TreeExplainer`), so no extra dependency is needed. Contributions are in log-odds of the
raw model: they rank the reasons; they are not probabilities and are never shown.
"""

from datetime import date

import numpy as np
import pandas as pd

from app.ml.calibrate import CalibratedModel
from app.ml.reasons import Reason, render

TOP_REASONS = 3


def contributions(fitted: CalibratedModel, features: pd.DataFrame) -> pd.DataFrame:
    """SHAP value of each feature per row; with the base value they sum to the raw margin."""
    booster = fitted.model.booster_
    if list(features.columns) != booster.feature_name():
        raise ValueError("feature columns do not match the columns the model was fitted on")
    raw = np.asarray(booster.predict(features, pred_contrib=True), dtype=float)
    return pd.DataFrame(raw[:, :-1], index=features.index, columns=features.columns)


def top_reasons(
    shap_values: pd.DataFrame, features: pd.DataFrame, as_of: date, k: int = TOP_REASONS
) -> dict[object, list[Reason]]:
    """Up to `k` reasons per row: features that push the score up the most, with a known value.

    The row labels become the `ref` in each `fact_id` (`ref/feature/as_of`); pass opaque case
    references, not names or roll numbers. A feature without a value (no data yet) is skipped,
    so a row can have fewer than `k` reasons, or none.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    if not (
        shap_values.index.equals(features.index) and shap_values.columns.equals(features.columns)
    ):
        raise ValueError("shap_values and features must have the same rows and columns")
    if not features.index.is_unique:
        raise ValueError("features has duplicate row labels, so fact_ids would collide")
    out: dict[object, list[Reason]] = {}
    for position, (ref, contribution) in enumerate(shap_values.iterrows()):
        values = features.iloc[position]
        ranked = contribution[(contribution > 0) & values.notna()].sort_values(
            ascending=False, kind="stable"
        )
        out[ref] = [
            Reason(
                fact_id=f"{ref}/{feature}/{as_of.isoformat()}",
                feature=str(feature),
                value=float(values[feature]),
                contribution=float(contribution[feature]),
                text=render(str(feature), float(values[feature])),
            )
            for feature in ranked.index[:k]
        ]
    return out
