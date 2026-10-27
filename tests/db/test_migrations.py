import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text

TEST_DB = os.environ.get("TEST_DATABASE_URL")
SCHEMAS = {"raw", "core", "ml", "app", "gov", "restricted"}


def _alembic(*args: str, url: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_offline_sql_generation_creates_every_schema() -> None:
    r = _alembic("upgrade", "head", "--sql", url="postgresql+psycopg://u:p@localhost/x")
    assert r.returncode == 0, r.stderr
    for schema in SCHEMAS:
        assert f"CREATE SCHEMA {schema}" in r.stdout


def test_missing_database_url_fails_loudly() -> None:
    r = _alembic("upgrade", "head", url="")
    assert r.returncode != 0
    assert "DATABASE_URL" in r.stderr


@pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")
def test_upgrade_downgrade_upgrade_on_empty_db() -> None:
    assert TEST_DB is not None
    for step in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
        r = _alembic(*step, url=TEST_DB)
        assert r.returncode == 0, r.stderr
    engine = create_engine(TEST_DB)
    with engine.connect() as conn:
        found = {
            row[0]
            for row in conn.execute(text("SELECT schema_name FROM information_schema.schemata"))
        }
        tables = conn.execute(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'")
        ).scalar_one()
    engine.dispose()
    assert found >= SCHEMAS
    assert tables == 10
    r = _alembic("downgrade", "base", url=TEST_DB)
    assert r.returncode == 0, r.stderr
