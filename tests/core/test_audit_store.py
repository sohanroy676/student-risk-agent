"""Audit writer and verifier against real Postgres (skipped without TEST_DATABASE_URL)."""

import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text

from app.core.audit import GENESIS, Anchor
from app.core.audit_store import append, current_anchor, main, verify

TEST_DB = os.environ.get("TEST_DATABASE_URL")
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
def engine() -> Iterator[Engine]:
    assert TEST_DB is not None
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    eng = create_engine(TEST_DB)
    try:
        yield eng
    finally:
        eng.dispose()
        _alembic("downgrade", "base")


def _add(engine: Engine, n: int = 1, action: str = "case.opened") -> None:
    for i in range(n):
        with engine.begin() as conn:
            append(
                conn,
                actor_kind="system",
                actor_id=None,
                action=action,
                subject_kind="case",
                subject_ref=f"case-{i}",
                detail={"i": i},
            )


def _check(engine: Engine, anchor: Anchor | None = None) -> Any:
    with engine.connect() as conn:
        return verify(conn, anchor)


def _tamper(engine: Engine, sql: str) -> None:
    """What an attacker with table-owner rights could do: switch the triggers off and edit."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE gov.audit_log DISABLE TRIGGER USER"))
        conn.execute(text(sql))
        conn.execute(text("ALTER TABLE gov.audit_log ENABLE TRIGGER USER"))


def test_an_empty_log_verifies_and_has_no_anchor(engine: Engine) -> None:
    result = _check(engine)
    assert result.ok and result.checked == 0 and result.head == GENESIS
    with engine.connect() as conn:
        assert current_anchor(conn) is None


def test_entries_form_one_numbered_chain_that_verifies(engine: Engine) -> None:
    _add(engine, 4)
    result = _check(engine)
    assert result.ok and result.checked == 4
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT seq, prev_hash, hash FROM gov.audit_log ORDER BY seq")
        ).all()
    assert [r.seq for r in rows] == [1, 2, 3, 4]
    assert rows[0].prev_hash == GENESIS
    assert all(rows[i].prev_hash == rows[i - 1].hash for i in range(1, 4))


def test_a_rolled_back_transaction_leaves_no_row_and_no_gap(engine: Engine) -> None:
    _add(engine, 1)
    with pytest.raises(RuntimeError), engine.begin() as conn:
        append(
            conn,
            actor_kind="system",
            actor_id=None,
            action="x.y",
            subject_kind="case",
            subject_ref=None,
        )
        raise RuntimeError("the change this entry describes failed")
    _add(engine, 1)
    result = _check(engine)
    assert result.ok and result.checked == 2


def test_a_malformed_or_banned_entry_is_refused_before_anything_is_written(
    engine: Engine,
) -> None:
    for detail in ({"student_name": "A"}, {"p": 0.5}):
        with pytest.raises(ValueError), engine.begin() as conn:
            append(
                conn,
                actor_kind="system",
                actor_id=None,
                action="x.y",
                subject_kind="case",
                subject_ref=None,
                detail=detail,
            )
    assert _check(engine).checked == 0


def test_concurrent_writers_still_produce_one_linear_chain(engine: Engine) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: _add(engine, 5), range(8)))
    result = _check(engine)
    assert result.ok and result.checked == 40


@pytest.mark.parametrize(
    ("sql", "bad_seq"),
    [
        ("UPDATE gov.audit_log SET action = 'case.dismissed' WHERE seq = 3", 3),
        ("UPDATE gov.audit_log SET detail = '{\"i\": 99}'::jsonb WHERE seq = 2", 2),
        ("UPDATE gov.audit_log SET actor_id = 'mallory' WHERE seq = 4", 4),
        ("DELETE FROM gov.audit_log WHERE seq = 3", 4),
    ],
)
def test_tampering_is_found_at_the_changed_row(engine: Engine, sql: str, bad_seq: int) -> None:
    _add(engine, 5)
    _tamper(engine, sql)
    result = _check(engine)
    assert not result.ok and result.first_bad_seq == bad_seq


def test_an_anchor_catches_cut_off_rows(engine: Engine) -> None:
    _add(engine, 3)
    with engine.connect() as conn:
        anchor = current_anchor(conn)
    assert anchor is not None and anchor.seq == 3
    _add(engine, 2)
    assert _check(engine, anchor).ok  # growth after the anchor is fine
    _tamper(engine, "DELETE FROM gov.audit_log WHERE seq > 2")
    cut = _check(engine, anchor)
    assert cut.ok is False and "cut off" in (cut.problem or "")


def test_the_cli_exit_codes_and_anchor_output(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert TEST_DB is not None
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    _add(engine, 3)
    assert main(["anchor"]) == 0
    saved = capsys.readouterr().out.strip()
    assert main(["verify", "--anchor", saved]) == 0
    _tamper(engine, "UPDATE gov.audit_log SET action = 'x.y' WHERE seq = 2")
    assert main(["verify"]) == 1
    assert "BROKEN at entry 2" in capsys.readouterr().out
