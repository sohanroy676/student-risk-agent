import os
import subprocess
import sys
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, create_engine, text

TEST_DB = os.environ.get("TEST_DATABASE_URL")


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
def conn() -> Iterator[Connection]:
    """Students 1-6 belong to mentor m1, on a throwaway database."""
    assert TEST_DB is not None
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    engine = create_engine(TEST_DB)
    try:
        with engine.begin() as setup:
            setup.execute(
                text("INSERT INTO core.terms VALUES (1, 'T', '2026-01-05', '2026-04-19')")
            )
            setup.execute(text("INSERT INTO core.sections VALUES (1, 'A', 1)"))
            for sid in range(1, 7):
                setup.execute(text("INSERT INTO core.students VALUES (:i, 1)"), {"i": sid})
                setup.execute(
                    text("INSERT INTO app.mentor_assignments VALUES (:i, 'm1')"), {"i": sid}
                )
        with engine.connect() as c:
            yield c
    finally:
        engine.dispose()
        _alembic("downgrade", "base")
