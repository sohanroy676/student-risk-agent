import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import timedelta

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sqlalchemy import create_engine

from app.features.db import load_core_tables
from app.features.snapshot import build_snapshot
from data.synthetic import generator
from data.synthetic.frames import to_core_tables, to_frames

TEST_DB = os.environ.get("TEST_DATABASE_URL")
# Parents before children so foreign keys hold.
LOAD_ORDER = (
    "terms",
    "sections",
    "courses",
    "students",
    "enrollments",
    "assessments",
    "marks",
    "attendance",
    "fees",
    "lms_events",
)

pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")


def _alembic(*args: str) -> None:
    assert TEST_DB is not None
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": TEST_DB},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr


@pytest.fixture
def loaded_db() -> Iterator[generator.SyntheticData]:
    assert TEST_DB is not None
    _alembic("upgrade", "head")
    data = generator.generate(seed=3)
    engine = create_engine(TEST_DB)
    try:
        frames = to_frames(data)
        with engine.begin() as conn:
            for name in LOAD_ORDER:
                frames[name].to_sql(
                    name, conn, schema="core", if_exists="append", index=False, chunksize=5000
                )
        yield data
    finally:
        engine.dispose()
        _alembic("downgrade", "base")


def test_database_snapshot_matches_in_memory_snapshot(
    loaded_db: generator.SyntheticData,
) -> None:
    assert TEST_DB is not None
    as_of = generator.TERM_START + timedelta(weeks=8, days=2)
    ids = list(range(1, generator.N_STUDENTS + 1))
    engine = create_engine(TEST_DB)
    try:
        with engine.connect() as conn:
            from_db = build_snapshot(load_core_tables(conn, as_of), ids, as_of)
    finally:
        engine.dispose()
    in_memory = build_snapshot(to_core_tables(loaded_db), ids, as_of)
    assert_frame_equal(from_db, in_memory)


def test_database_rows_after_as_of_are_not_loaded(loaded_db: generator.SyntheticData) -> None:
    assert TEST_DB is not None
    as_of = generator.TERM_START + timedelta(weeks=2)
    engine = create_engine(TEST_DB)
    try:
        with engine.connect() as conn:
            tables = load_core_tables(conn, as_of)
    finally:
        engine.dispose()
    cutoff = pd.Timestamp(as_of)
    assert tables.attendance["class_date"].max() <= cutoff
    assert tables.lms_events["occurred_at"].max() < cutoff + pd.Timedelta(days=1)
    assert tables.marks["submitted_on"].max() <= cutoff
    assert (tables.fees["paid_on"].dropna() <= cutoff).all()
    assert {"forum_post", "quiz_attempt"} <= set(tables.lms_events["event_type"])
