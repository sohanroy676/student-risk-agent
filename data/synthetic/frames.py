"""Turn generated synthetic tables into the frames the feature builder consumes."""

import pandas as pd

from app.features.tables import CoreTables
from data.synthetic.generator import SyntheticData


def to_frames(data: SyntheticData) -> dict[str, pd.DataFrame]:
    return {
        name: pd.DataFrame(table.rows, columns=list(table.columns))
        for name, table in data.tables.items()
    }


def to_core_tables(data: SyntheticData) -> CoreTables:
    return CoreTables.from_frames(**to_frames(data))
