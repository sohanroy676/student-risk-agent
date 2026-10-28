"""Isotonic calibration of the production model, plus calibration and ranking metrics.

The training years are split by `term_start`: the latest presentation among the training rows
is the validation set, everything earlier fits the model. The isotonic map is fitted on the
model's scores for the validation set only. Test rows are never passed to either fit.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

from app.features.tables import CoreTables
from app.ml.baseline import MODELS, PRODUCTION, WEEKS, check_cohort, weekly_matrix

ECE_TARGET = 0.05
LIFT_TARGET = 2.0
TOP_FRACTION = 0.1


def ece(y: ArrayLike, p: ArrayLike, bins: int = 10) -> float:
    """Expected calibration error: bin-size-weighted gap between mean outcome and mean score."""
    y_arr = np.asarray(y, dtype=float)
    p_arr = np.asarray(p, dtype=float)
    if y_arr.shape != p_arr.shape or y_arr.ndim != 1:
        raise ValueError("y and p must be 1-D arrays of the same length")
    if y_arr.size == 0:
        raise ValueError("ece needs at least one row")
    if not np.isin(y_arr, (0.0, 1.0)).all():
        raise ValueError("y must be binary")
    if np.isnan(p_arr).any() or ((p_arr < 0) | (p_arr > 1)).any():
        raise ValueError("p must be probabilities in [0, 1]")
    if bins < 1:
        raise ValueError("bins must be at least 1")
    # Equal-width bins; a score of exactly 1.0 belongs to the last bin.
    index = np.minimum((p_arr * bins).astype(int), bins - 1)
    total = 0.0
    for b in range(bins):
        in_bin = index == b
        if in_bin.any():
            total += in_bin.sum() * abs(y_arr[in_bin].mean() - p_arr[in_bin].mean())
    return float(total / y_arr.size)


def precision_at_top(y: ArrayLike, score: ArrayLike, frac: float = TOP_FRACTION) -> float:
    """Share of true positives among the top `frac` of rows by score (ties keep input order)."""
    if not 0 < frac <= 1:
        raise ValueError("frac must be in (0, 1]")
    y_arr = np.asarray(y, dtype=float)
    s_arr = np.asarray(score, dtype=float)
    if y_arr.shape != s_arr.shape or y_arr.ndim != 1:
        raise ValueError("y and score must be 1-D arrays of the same length")
    if y_arr.size == 0:
        raise ValueError("precision_at_top needs at least one row")
    if np.isnan(s_arr).any():
        raise ValueError("score must not contain NaN")
    k = max(1, math.ceil(frac * y_arr.size))
    top = np.argsort(-s_arr, kind="stable")[:k]
    return float(y_arr[top].mean())


@dataclass(frozen=True)
class CalibratedModel:
    """A fitted model, its isotonic map and the student ids each was fitted on."""

    model: Any
    calibrator: IsotonicRegression
    fit_index: pd.Index
    validation_index: pd.Index

    def raw_score(self, features: pd.DataFrame) -> NDArray[np.float64]:
        return np.asarray(self.model.predict_proba(features)[:, 1], dtype=float)

    def predict_proba(self, features: pd.DataFrame) -> NDArray[np.float64]:
        return np.asarray(self.calibrator.predict(self.raw_score(features)), dtype=float)


def fit_calibrated(
    features: pd.DataFrame, y: pd.Series, term_start: pd.Series, model_name: str = PRODUCTION
) -> CalibratedModel:
    """Fit on the earlier training presentations, calibrate on the latest one.

    Pass training rows only. Raises if there is just one presentation or either part lacks
    a class, rather than falling back to a random split that would leak across presentations.
    """
    if not (features.index.equals(y.index) and features.index.equals(term_start.index)):
        raise ValueError("features, y and term_start must share the same index")
    latest = term_start.max()
    if term_start.nunique() < 2:
        raise ValueError("calibration needs at least two training presentations")
    is_validation = term_start == latest
    for part, name in ((~is_validation, "fit"), (is_validation, "validation")):
        if y[part].nunique() < 2:
            raise ValueError(f"the {name} part needs both classes")
    model = MODELS[model_name]().fit(features[~is_validation], y[~is_validation])
    raw = model.predict_proba(features[is_validation])[:, 1]
    calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    calibrator.fit(raw, y[is_validation].astype(float))
    return CalibratedModel(
        model, calibrator, features.index[~is_validation], features.index[is_validation]
    )


def evaluate_calibrated(
    tables: CoreTables, cohort: pd.DataFrame, weeks: Sequence[int] = WEEKS
) -> pd.DataFrame:
    """One row per week of calibration and top-10% results for the production model on test.

    `top10_precision` ranks by the raw model score: isotonic output is monotone but has
    plateaus, and ties would make the cut-off depend on row order.
    """
    check_cohort(cohort)
    rows = []
    for week in weeks:
        features, y, split = weekly_matrix(tables, cohort, week)
        train, test = split == "train", split == "test"
        row: dict[str, float | int | bool] = {
            "week": week,
            "auc_cal": float("nan"),
            "ece_raw": float("nan"),
            "ece": float("nan"),
            "top10_precision": float("nan"),
            "top10_lift": float("nan"),
            "ece_ok": False,
            "lift_ok": False,
        }
        if train.any() and test.any() and y[test].nunique() == 2:
            starts = cohort.loc[features.index[train], "term_start"]
            fitted = fit_calibrated(features[train], y[train], starts)
            raw, cal = fitted.raw_score(features[test]), fitted.predict_proba(features[test])
            base = float(y[test].mean())
            top = precision_at_top(y[test], raw)
            row.update(
                auc_cal=float(roc_auc_score(y[test], cal)),
                ece_raw=ece(y[test], raw),
                ece=ece(y[test], cal),
                top10_precision=top,
                top10_lift=top / base,
            )
            row["ece_ok"] = bool(row["ece"] <= ECE_TARGET)
            row["lift_ok"] = bool(row["top10_lift"] >= LIFT_TARGET)
        rows.append(row)
    return pd.DataFrame(rows)
