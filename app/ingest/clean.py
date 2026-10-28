"""Turn raw (all-text) source tables into typed core tables, and record what was wrong.

A row that cannot be trusted is rejected (never repaired or guessed); a row that is odd but
usable is kept and noted as a warning. Rules, in the order they are applied per table:

1. `missing_required` / `bad_value`: a required value is empty, or any value does not parse.
2. `out_of_range`: negative marks, non-positive fees or maximum marks, a term that ends
   before it starts.
3. `duplicate_key`: the same key appears twice with different values; the later row wins.
   Exact copies of a row are dropped silently (they carry no information).
4. `duplicate_unique`: a second row reuses a unique value (a course code); the first wins.
5. `orphan_fk`: the row points at a parent that is missing or was itself rejected.

Warnings on kept rows: `marks_above_max`, `mark_without_date`, `future_date`.

Tables are cleaned parents first, so one bad student also drops that student's children.
Rows are identified by their source row number, never by value.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.ingest.schema import SPECS, Column, TableSpec

ROW = "_row"
MAX_SAMPLE_ROWS = 5
INT_LIMIT = 2**31 - 1
TRUE_WORDS = frozenset({"true", "t", "1", "yes", "y", "present", "p"})
FALSE_WORDS = frozenset({"false", "f", "0", "no", "n", "absent", "a"})
# Date columns that should not lie after the run date.
FUTURE_CHECKED = {
    "attendance": "class_date",
    "marks": "submitted_on",
    "fees": "paid_on",
    "lms_events": "occurred_at",
}


@dataclass(frozen=True)
class Issue:
    table: str
    code: str
    count: int
    rejected: bool
    # Source row numbers of the first few affected rows.
    rows: tuple[int, ...] = ()


@dataclass
class CleanResult:
    tables: dict[str, pd.DataFrame]
    rows_in: dict[str, int]
    issues: list[Issue] = field(default_factory=list)

    def count(self, table: str, code: str) -> int:
        return sum(i.count for i in self.issues if i.table == table and i.code == code)

    def rejected(self, table: str) -> int:
        return sum(i.count for i in self.issues if i.table == table and i.rejected)


def _parse(text: pd.Series, column: Column) -> tuple[pd.Series, pd.Series]:
    """Typed values and a mask of non-empty cells that failed to parse."""
    empty = text == ""
    filled = text.where(~empty)
    if column.kind == "text":
        return text, pd.Series(False, index=text.index)
    if column.kind in ("int", "num"):
        number = pd.to_numeric(filled, errors="coerce").astype("float64")
        bad = ~empty & (number.isna() | ~np.isfinite(number))
        if column.kind == "int":
            bad |= ~empty & ((number % 1 != 0) | (number.abs() > INT_LIMIT))
            return number.where(~bad).astype("Int64"), bad
        return number.where(~bad), bad
    if column.kind == "bool":
        lowered = text.str.lower()
        is_true, is_false = lowered.isin(TRUE_WORDS), lowered.isin(FALSE_WORDS)
        bad = ~empty & ~is_true & ~is_false
        return pd.Series(is_true.to_numpy(), index=text.index), bad
    stamp = pd.to_datetime(filled, format="ISO8601", errors="coerce")
    bad = ~empty & stamp.isna()
    if column.kind == "date":
        stamp = stamp.dt.normalize()
    return stamp, bad


class _TableCleaner:
    def __init__(self, spec: TableSpec, raw: pd.DataFrame) -> None:
        self.spec = spec
        missing = set(spec.column_names) - set(raw.columns)
        if missing:
            raise ValueError(f"{spec.name} is missing columns: {sorted(missing)}")
        self.rows = raw[ROW].astype(int).reset_index(drop=True)
        self.text = {
            c: raw[c].astype(str).str.strip().reset_index(drop=True) for c in spec.column_names
        }
        self.alive = pd.Series(True, index=self.rows.index)
        self.issues: list[Issue] = []

    def note(self, mask: pd.Series, code: str, rejected: bool) -> None:
        hit = mask & self.alive
        if hit.any():
            sample = tuple(int(r) for r in self.rows[hit].head(MAX_SAMPLE_ROWS))
            self.issues.append(Issue(self.spec.name, code, int(hit.sum()), rejected, sample))
        if rejected:
            self.alive &= ~hit

    def run(self, cleaned: Mapping[str, pd.DataFrame], run_date: date) -> pd.DataFrame:
        spec = self.spec
        typed: dict[str, pd.Series] = {}
        for column in spec.columns:
            values, bad = _parse(self.text[column.name], column)
            typed[column.name] = values
            empty = self.text[column.name] == ""
            if column.required:
                self.note(empty, "missing_required", True)
            self.note(bad, "bad_value", True)
            if column.kind == "num" and column.minimum is not None:
                low = values <= column.minimum if column.positive else values < column.minimum
                self.note(low.fillna(False), "out_of_range", True)
        if spec.name == "terms":
            self.note(typed["end_date"] <= typed["start_date"], "out_of_range", True)
        frame = pd.DataFrame(typed)
        key = list(spec.key)
        self.alive &= ~frame[self.alive].duplicated(keep="last").reindex(
            frame.index, fill_value=False
        )
        # `alive` rows only: a rejected duplicate must not push out a good row.
        later_exists = (
            frame[self.alive].duplicated(key, keep="last").reindex(frame.index, fill_value=False)
        )
        self.note(later_exists, "duplicate_key", True)
        for column_name in spec.unique:
            again = (
                frame[self.alive]
                .duplicated(column_name, keep="first")
                .reindex(frame.index, fill_value=False)
            )
            self.note(again, "duplicate_unique", True)
        for column_name, parent in spec.parents:
            self.note(~frame[column_name].isin(cleaned[parent]["id"]), "orphan_fk", True)
        self._warn(frame, cleaned, run_date)
        return frame[self.alive].reset_index(drop=True)

    def _warn(
        self, frame: pd.DataFrame, cleaned: Mapping[str, pd.DataFrame], run_date: date
    ) -> None:
        name = self.spec.name
        if name == "marks":
            limit = cleaned["assessments"].set_index("id")["max_marks"]
            above = frame["marks_obtained"] > frame["assessment_id"].map(limit)
            self.note(above.fillna(False), "marks_above_max", False)
            undated = frame["marks_obtained"].notna() & frame["submitted_on"].isna()
            self.note(undated, "mark_without_date", False)
        if name in FUTURE_CHECKED:
            future = frame[FUTURE_CHECKED[name]] > pd.Timestamp(run_date) + pd.Timedelta(days=1)
            self.note(future.fillna(False), "future_date", False)


def clean(raw: Mapping[str, pd.DataFrame], run_date: date) -> CleanResult:
    """Clean every table in `SPECS` order. Absent optional tables come back empty."""
    cleaned: dict[str, pd.DataFrame] = {}
    rows_in: dict[str, int] = {}
    issues: list[Issue] = []
    for spec in SPECS:
        frame = raw.get(spec.name)
        rows_in[spec.name] = 0 if frame is None else len(frame)
        if frame is None or frame.empty:
            cleaned[spec.name] = _empty(spec)
            continue
        worker = _TableCleaner(spec, frame)
        cleaned[spec.name] = worker.run(cleaned, run_date)
        issues.extend(worker.issues)
    return CleanResult(cleaned, rows_in, issues)


def _empty(spec: TableSpec) -> pd.DataFrame:
    dtypes = {"int": "Int64", "num": "float64", "bool": "bool", "text": "str"}
    return pd.DataFrame(
        {c.name: pd.Series(dtype=dtypes.get(c.kind, "datetime64[ns]")) for c in spec.columns}
    )
