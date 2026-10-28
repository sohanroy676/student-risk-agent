from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import create_engine, text

from app.api import admin, cases, models
from app.core.settings import Settings, get_settings

app = FastAPI(title="Student Risk Agent")
app.include_router(cases.router)
app.include_router(admin.router)
app.include_router(models.router)


def _db_ok(settings: Settings) -> bool:
    if not settings.database_url:
        return False
    try:
        engine = create_engine(settings.database_url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        return False
    return True


def _redis_ok(settings: Settings) -> bool:
    if not settings.redis_url:
        return False
    try:
        return bool(Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping())
    except Exception:
        return False


@app.get("/health")
def health() -> JSONResponse:
    settings = get_settings()
    checks = {"db": _db_ok(settings), "redis": _redis_ok(settings)}
    ok = all(checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", **checks}, status_code=200 if ok else 503
    )
