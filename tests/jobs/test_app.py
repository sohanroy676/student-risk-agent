import pytest
from celery.schedules import crontab

from app.core.settings import Settings
from app.jobs import (
    NIGHTLY_HOUR,
    NIGHTLY_TASK,
    VISIBILITY_TIMEOUT_S,
    _require_broker,
    make_celery,
)
from app.jobs import app as default_app


def settings(**values: str) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_broker_and_timezone_come_from_settings() -> None:
    app = make_celery(settings(redis_url="redis://r:6379/0", app_timezone="Asia/Kolkata"))
    assert app.conf.broker_url == "redis://r:6379/0"
    assert app.conf.timezone == "Asia/Kolkata"


def test_without_redis_the_app_still_builds_on_the_memory_broker() -> None:
    assert make_celery(settings(redis_url="")).conf.broker_url == "memory://"


def test_nightly_is_scheduled_once_a_day_at_the_configured_hour() -> None:
    entry = make_celery(settings()).conf.beat_schedule["nightly"]
    assert entry["task"] == NIGHTLY_TASK
    assert entry["schedule"] == crontab(hour=NIGHTLY_HOUR, minute=0)


def test_tasks_use_json_only_and_are_not_redelivered_mid_run() -> None:
    conf = make_celery(settings()).conf
    assert conf.task_serializer == "json" and list(conf.accept_content) == ["json"]
    assert conf.task_acks_late and conf.worker_prefetch_multiplier == 1
    assert conf.broker_transport_options["visibility_timeout"] == VISIBILITY_TIMEOUT_S
    assert conf.task_time_limit < VISIBILITY_TIMEOUT_S


def test_a_worker_refuses_to_start_without_a_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.chdir("tests")  # keep a developer's .env out of the test
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        _require_broker()


def test_a_worker_starts_when_a_broker_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://r:6379/0")
    _require_broker()


def test_default_app_is_importable_by_the_cli() -> None:
    assert default_app.main == "risk"
