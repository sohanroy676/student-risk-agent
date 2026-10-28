"""Idempotent loading into Postgres: raw tables first, then cleaned core tables.

Every statement is an upsert on the table's natural key, so loading the same files twice
changes nothing. Rows that vanish from a later file are not deleted (the connector only
adds and updates); `raw.dq_reports` keeps one report per run date and source.
Identifiers in the SQL come from `app.ingest.schema`, never from input.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import Connection, text

from app.ingest.clean import CleanResult, clean
from app.ingest.quality import DataQualityReport, build_report
from app.ingest.schema import SPECS, TableSpec

CHUNK = 5000


def _upsert_sql(schema: str, spec: TableSpec) -> str:
    cols = spec.column_names
    update = [c for c in cols if c not in spec.key]
    action = (
        "DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in update)
        if update
        else "DO NOTHING"
    )
    return (
        f"INSERT INTO {schema}.{spec.name} ({', '.join(cols)}) "  # noqa: S608
        f"VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT ({', '.join(spec.key)}) {action}"
    )


def _python(value: Any, kind: str) -> Any:
    if pd.isna(value):
        return None
    if kind == "date":
        return value.date()
    if kind == "datetime":
        return value.to_pydatetime()
    if kind == "bool":
        return bool(value)
    if kind == "int":
        return int(value)
    if kind == "num":
        return float(value)
    return str(value)


def _records(frame: pd.DataFrame, spec: TableSpec) -> list[dict[str, Any]]:
    columns = {c.name: [_python(v, c.kind) for v in frame[c.name]] for c in spec.columns}
    return [dict(zip(columns, row, strict=True)) for row in zip(*columns.values(), strict=True)]


def _execute_chunks(conn: Connection, sql: str, records: list[dict[str, Any]]) -> None:
    for start in range(0, len(records), CHUNK):
        conn.execute(text(sql), records[start : start + CHUNK])


def load_raw(conn: Connection, raw: Mapping[str, pd.DataFrame]) -> None:
    """Upsert source rows as text; a repeated key keeps the last row in the file."""
    for spec in SPECS:
        frame = raw.get(spec.name)
        if frame is None or frame.empty:
            continue
        frame = frame.drop_duplicates(list(spec.key), keep="last")
        rows = frame[spec.column_names].astype(str).to_dict("records")
        _execute_chunks(conn, _upsert_sql("raw", spec), rows)  # type: ignore[arg-type]


def load_core(conn: Connection, result: CleanResult) -> None:
    for spec in SPECS:
        frame = result.tables[spec.name]
        if not frame.empty:
            _execute_chunks(conn, _upsert_sql(spec.schema, spec), _records(frame, spec))


def store_report(conn: Connection, report: DataQualityReport, source: str) -> None:
    conn.execute(
        text(
            "INSERT INTO raw.dq_reports (run_date, source, status, report) "
            "VALUES (:run_date, :source, :status, CAST(:report AS jsonb)) "
            "ON CONFLICT (run_date, source) DO UPDATE SET "
            "status = EXCLUDED.status, report = EXCLUDED.report, created_at = now()"
        ),
        {
            "run_date": report.run_date,
            "source": source,
            "status": report.status,
            "report": report.to_json(),
        },
    )


def ingest(
    conn: Connection, raw: Mapping[str, pd.DataFrame], run_date: date, source: str
) -> tuple[CleanResult, DataQualityReport]:
    """Load raw, clean, and (unless the report says `fail`) load core. Always stores the report."""
    load_raw(conn, raw)
    result = clean(raw, run_date)
    report = build_report(result, run_date)
    if report.status != "fail":
        load_core(conn, result)
    store_report(conn, report, source)
    return result, report
