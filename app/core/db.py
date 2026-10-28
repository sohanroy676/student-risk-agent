"""One shared engine, and how a request's transaction is tied to the person making it.

`scope_to_principal` first records who is asking (`app.user_id`, `app.role`, both
transaction-local), then drops to `app_api_role`, which owns nothing and is subject to the
row-level-security policies of migration 0007. Both settings vanish when the transaction ends, so
a pooled connection never carries one request's identity into the next. The login that the API
connects with must be allowed to `SET ROLE app_api_role` (the table owner always is).
"""

from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine, text

from app.core.settings import get_settings

API_ROLE = "app_api_role"


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(url, pool_pre_ping=True)


def scope_to_principal(conn: Connection, subject: str, role: str) -> None:
    """Call first thing in a transaction, before any query on behalf of a request."""
    conn.execute(
        text(
            "SELECT set_config('app.user_id', :subject, true), set_config('app.role', :role, true)"
        ),
        {"subject": subject, "role": role},
    )
    conn.execute(text(f"SET LOCAL ROLE {API_ROLE}"))
