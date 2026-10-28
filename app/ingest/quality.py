"""Nightly data-quality report built from a `CleanResult`.

Status rules (defaults chosen before seeing real college data; tune them on first contact):
- `fail`: an essential table has no usable rows, or more than `MAX_REJECT_SHARE` of a
  table's rows were rejected.
- `warn`: any rejected row, any warning, or attendance/LMS data whose newest date is more than
  `STALE_DAYS` before the run date.
- `ok`: otherwise.
The report holds counts, dates and source row numbers only, never student values.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

import pandas as pd

from app.ingest.clean import CleanResult
from app.ingest.schema import ESSENTIAL, FRESHNESS, SPECS, STREAMING

MAX_REJECT_SHARE = 0.05
STALE_DAYS = 3

Status = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class TableReport:
    table: str
    rows_in: int
    rows_loaded: int
    rejected: int
    newest: str | None


@dataclass(frozen=True)
class DataQualityReport:
    run_date: str
    status: Status
    tables: list[TableReport]
    issues: list[dict[str, object]]
    problems: list[str] = field(default_factory=list)
    students_without_enrollment: int = 0
    enrolled_without_attendance: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    def render(self) -> str:
        lines = [f"Data quality {self.run_date}: {self.status.upper()}", ""]
        lines += [
            f"- {t.table}: {t.rows_loaded}/{t.rows_in} loaded, {t.rejected} rejected"
            + (f", newest {t.newest}" if t.newest else "")
            for t in self.tables
        ]
        lines.append(f"- students with no enrollment: {self.students_without_enrollment}")
        lines.append(f"- enrolled students with no attendance: {self.enrolled_without_attendance}")
        if self.problems:
            lines += ["", "Problems:", *[f"- {p}" for p in self.problems]]
        if self.issues:
            lines += ["", "Issues (table, code, count, first source rows):"]
            lines += [
                f"- {i['table']} {i['code']} x{i['count']} rows {i['rows']}" for i in self.issues
            ]
        return "\n".join(lines)


def _newest(frame: pd.DataFrame, column: str) -> pd.Timestamp | None:
    if column not in frame or frame[column].dropna().empty:
        return None
    return pd.Timestamp(frame[column].max())


def build_report(result: CleanResult, run_date: date) -> DataQualityReport:
    failures: list[str] = []
    stale: list[str] = []
    tables: list[TableReport] = []
    for spec in SPECS:
        frame = result.tables[spec.name]
        rows_in, rejected = result.rows_in[spec.name], result.rejected(spec.name)
        newest = _newest(frame, FRESHNESS[spec.name]) if spec.name in FRESHNESS else None
        tables.append(
            TableReport(
                spec.name, rows_in, len(frame), rejected, None if newest is None else str(newest)
            )
        )
        if rows_in and rejected / rows_in > MAX_REJECT_SHARE:
            failures.append(f"{spec.name}: {rejected} of {rows_in} rows rejected")
        if (
            newest is not None
            and spec.name in STREAMING
            and (pd.Timestamp(run_date) - newest).days > STALE_DAYS
        ):
            stale.append(
                f"{spec.name}: newest data is {newest.date()}, older than {STALE_DAYS} days"
            )
    for name in ESSENTIAL:
        if result.tables[name].empty:
            failures.append(f"{name}: no usable rows")
    students = set(result.tables["students"]["id"])
    enrolled = set(result.tables["enrollments"]["student_id"])
    attended = set(result.tables["attendance"]["student_id"])
    status: Status = "fail" if failures else "warn" if stale or result.issues else "ok"
    return DataQualityReport(
        run_date=run_date.isoformat(),
        status=status,
        tables=tables,
        issues=[asdict(i) for i in result.issues],
        problems=failures + stale,
        students_without_enrollment=len(students - enrolled),
        enrolled_without_attendance=len(enrolled - attended),
    )
