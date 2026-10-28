"""CSV connector: read one folder of ERP exports, check it, and (optionally) load it.

    python -m app.ingest.csv_connector DIR --dry-run     # report only, no database
    python -m app.ingest.csv_connector DIR               # load into DATABASE_URL

Files are named after the tables in `app.ingest.schema` (`students.csv`, ...). Other files
in the folder are ignored. Everything is read as text; parsing happens in the cleaner.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

from app.core.settings import get_settings
from app.ingest.clean import ROW, CleanResult, clean
from app.ingest.db import ingest
from app.ingest.quality import DataQualityReport, build_report
from app.ingest.schema import SPECS


def read_csv_dir(directory: Path) -> dict[str, pd.DataFrame]:
    """Raw text frames with a `_row` column holding the line number in the source file."""
    if not directory.is_dir():
        raise FileNotFoundError(f"{directory} is not a folder")
    frames: dict[str, pd.DataFrame] = {}
    for spec in SPECS:
        path = directory / f"{spec.name}.csv"
        if not path.is_file():
            continue
        try:
            frame = pd.read_csv(
                path, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8-sig"
            )
        except (pd.errors.ParserError, UnicodeDecodeError) as exc:
            raise ValueError(f"{path.name} cannot be read as CSV: {exc}") from exc
        frame.columns = pd.Index([str(c).strip().lower() for c in frame.columns])
        frame[ROW] = range(2, len(frame) + 2)
        frames[spec.name] = frame
    return frames


def check_csv_dir(directory: Path, run_date: date) -> tuple[CleanResult, DataQualityReport]:
    """Clean a folder and build the report without touching any database."""
    result = clean(read_csv_dir(directory), run_date)
    return result, build_report(result, run_date)


def ingest_csv_dir(database_url: str, directory: Path, run_date: date) -> DataQualityReport:
    raw = read_csv_dir(directory)
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            _, report = ingest(conn, raw, run_date, source=f"csv:{directory.name}")
    finally:
        engine.dispose()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--run-date", type=date.fromisoformat, default=None)
    parser.add_argument("--dry-run", action="store_true", help="report only; no database")
    args = parser.parse_args(argv)
    run_date = args.run_date or date.today()
    if args.dry_run:
        report = check_csv_dir(args.directory, run_date)[1]
    else:
        url = get_settings().database_url
        if not url:
            parser.error("DATABASE_URL is not set (use --dry-run to only check the files)")
        report = ingest_csv_dir(url, args.directory, run_date)
    print(report.render())
    return 1 if report.status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
