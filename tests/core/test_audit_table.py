"""gov.audit_log against real Postgres (skipped without TEST_DATABASE_URL; CI runs it)."""

import os
import subprocess
import sys
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")

INSERT = text(
    "INSERT INTO gov.audit_log (seq, at, actor_kind, action, subject_kind, prev_hash, hash) "
    "VALUES (:seq, now(), 'system', 'case.opened', 'case', :prev, :hash)"
)
H0, H1, H2 = "0" * 64, "1" * 64, "2" * 64


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
def engine() -> Iterator[Engine]:
    assert TEST_DB is not None
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    eng = create_engine(TEST_DB)
    try:
        with eng.begin() as conn:
            conn.execute(INSERT, {"seq": 1, "prev": H0, "hash": H1})
        yield eng
    finally:
        eng.dispose()
        _alembic("downgrade", "base")


def _count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM gov.audit_log")).scalar_one())


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE gov.audit_log SET action = 'x'",
        "DELETE FROM gov.audit_log",
        "TRUNCATE gov.audit_log",
    ],
)
def test_the_log_refuses_changes_deletes_and_truncation(engine: Engine, statement: str) -> None:
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
        conn.execute(text(statement))
    assert _count(engine) == 1


def test_a_second_row_pointing_at_the_same_predecessor_is_refused(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(INSERT, {"seq": 2, "prev": H0, "hash": H2})
    assert _count(engine) == 1


def test_the_next_row_in_the_chain_is_accepted(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(INSERT, {"seq": 2, "prev": H1, "hash": H2})
    assert _count(engine) == 2


@pytest.mark.parametrize(
    ("seq", "prev", "hash_"),
    [(0, H1, H2), (2, "short", H2), (2, H1, "G" * 64), (2, H1, H1), (1, H1, H2)],
)
def test_malformed_or_repeated_rows_are_refused(
    engine: Engine, seq: int, prev: str, hash_: str
) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(INSERT, {"seq": seq, "prev": prev, "hash": hash_})
    assert _count(engine) == 1


def test_migration_0005_downgrades_and_upgrades_again(engine: Engine) -> None:
    engine.dispose()
    _alembic("downgrade", "0004")
    _alembic("upgrade", "head")
    with create_engine(TEST_DB or "").connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM gov.audit_log")).scalar_one() == 0
