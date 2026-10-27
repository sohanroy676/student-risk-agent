"""Load the UCI "Predict students' dropout and academic success" dataset.

This dataset is a one-row-per-student table with no event dates, so it cannot feed the
`as_of` snapshot builder. It is used as a cross-check for the baseline model. Column
names are normalised to snake_case, protected attributes are split into their own
frame, and the label is `Target == "Dropout"`.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

AT_RISK_TARGET = "Dropout"
PROTECTED_COLUMNS = (
    "gender",
    "nationality",
    "nacionality",  # the published file's own spelling
    "marital_status",
    "age_at_enrollment",
    "international",
    "displaced",
    "educational_special_needs",
)


@dataclass
class UciData:
    features: pd.DataFrame
    attributes: pd.DataFrame
    labels: pd.Series  # bool, True = dropout


def _snake(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", name.strip().lower()).strip("_")


def load_uci(path: Path) -> UciData:
    if not path.is_file():
        raise ValueError(f"UCI file missing: {path}")
    # The published file is semicolon-separated; fall back to commas for re-exports.
    frame = pd.read_csv(path, sep=None, engine="python")
    frame.columns = pd.Index([_snake(c) for c in frame.columns])
    if "target" not in frame.columns:
        raise ValueError("UCI file has no 'Target' column")
    if frame.columns.duplicated().any():
        raise ValueError("UCI file has columns that collide after normalisation")

    labels = (frame["target"].astype(str).str.strip() == AT_RISK_TARGET).rename("at_risk")
    protected = [c for c in PROTECTED_COLUMNS if c in frame.columns]
    attributes = frame[protected].copy()
    features = frame.drop(columns=["target", *protected])
    return UciData(
        features=features.reset_index(drop=True),
        attributes=attributes.reset_index(drop=True),
        labels=labels.reset_index(drop=True),
    )
