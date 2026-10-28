"""Celery app and beat schedule. Run with `celery -A app.jobs worker|beat -l info`."""

from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_init

from app.core.settings import Settings, get_settings

NIGHTLY_TASK = "app.jobs.nightly.run_nightly"
NIGHTLY_HOUR = 1
# A night's run is idempotent but long; keep Redis from redelivering it while it still runs.
VISIBILITY_TIMEOUT_S = 2 * 60 * 60
TIME_LIMIT_S = 60 * 60


def make_celery(settings: Settings) -> Celery:
    """Build the app; with no REDIS_URL it uses an in-process broker so imports still work."""
    app = Celery(
        "risk",
        broker=settings.redis_url or "memory://",
        include=["app.jobs.nightly"],
        set_as_current=False,
    )
    app.conf.update(
        timezone=settings.app_timezone,
        enable_utc=True,
        task_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_time_limit=TIME_LIMIT_S,
        broker_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_S},
        beat_schedule={
            "nightly": {"task": NIGHTLY_TASK, "schedule": crontab(hour=NIGHTLY_HOUR, minute=0)},
        },
    )
    return app


app = make_celery(get_settings())


def _require_broker(**_: Any) -> None:
    """A worker on the in-process broker would sit idle forever, so refuse to start."""
    if not get_settings().redis_url:
        raise RuntimeError("REDIS_URL is not set; the worker has no broker to read from")


worker_init.connect(_require_broker)
