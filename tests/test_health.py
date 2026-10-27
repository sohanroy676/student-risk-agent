import pytest
from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def _set(monkeypatch: pytest.MonkeyPatch, db: bool, redis: bool) -> None:
    monkeypatch.setattr(main, "_db_ok", lambda _s: db)
    monkeypatch.setattr(main, "_redis_ok", lambda _s: redis)


def test_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, True, True)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True, "redis": True}


@pytest.mark.parametrize(("db", "redis"), [(False, True), (True, False), (False, False)])
def test_health_degraded_when_a_dependency_is_down(
    monkeypatch: pytest.MonkeyPatch, db: bool, redis: bool
) -> None:
    _set(monkeypatch, db, redis)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"


def test_unconfigured_services_report_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    settings = main.Settings(_env_file=None)  # type: ignore[call-arg]
    assert main._db_ok(settings) is False
    assert main._redis_ok(settings) is False


def test_unreachable_services_do_not_raise() -> None:
    settings = main.Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="postgresql+psycopg://u:p@127.0.0.1:1/x",
        redis_url="redis://127.0.0.1:1/0",
    )
    assert main._db_ok(settings) is False
    assert main._redis_ok(settings) is False
