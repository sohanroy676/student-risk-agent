"""A synthetic college and a small calibrated model fitted on it, shared by the nightly tests."""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from app.features.snapshot import build_snapshot
from app.features.tables import CoreTables
from app.ml.calibrate import CalibratedModel, fit_calibrated
from data.synthetic import generator
from data.synthetic.frames import to_core_tables

AS_OF = generator.TERM_START + timedelta(weeks=8, days=2)
IDS = list(range(1, generator.N_STUDENTS + 1))


@pytest.fixture(scope="module")
def tables() -> CoreTables:
    return to_core_tables(generator.generate(seed=3))


@pytest.fixture(scope="module")
def model(tables: CoreTables) -> CalibratedModel:
    features = build_snapshot(tables, IDS, AS_OF)
    y = pd.Series(features["attendance_rate"].fillna(0) < features["attendance_rate"].median())
    half = np.arange(len(features)) < len(features) // 2
    starts = pd.Series(
        pd.to_datetime(np.where(half, "2013-02-01", "2013-10-01")), index=features.index
    )
    return fit_calibrated(features, y, starts)
