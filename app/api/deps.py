"""FastAPI dependencies: who is calling, may they, and a database transaction scoped to them.

Failures say as little as possible: a bad token is a plain 401 with no reason, and a case the
caller may not see is the route's business (404), not a 403 here. Every 403 for an
authenticated caller is recorded in the audit log (role and route template only).
"""

import logging
from collections.abc import Callable, Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Connection

from app.core import audit_store
from app.core.auth import (
    AuthError,
    Forbidden,
    Principal,
    Role,
    TokenVerifier,
    allow,
    build_verifier,
)
from app.core.db import get_engine, scope_to_principal
from app.core.settings import get_settings

log = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)
Denial = Callable[[str, str, str, str], None]  # subject, role, method, route template


@lru_cache
def configured_verifier() -> TokenVerifier:
    settings = get_settings()
    return build_verifier(
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        public_key=settings.jwt_public_key,
        jwks_url=settings.jwt_jwks_url,
        roles_claim=settings.jwt_roles_claim,
    )


def get_verifier() -> TokenVerifier:
    try:
        return configured_verifier()
    except ValueError as error:
        log.error("authentication is not configured: %s", error)
        raise HTTPException(503, "authentication is not configured") from error


def record_denial(subject: str, role: str, method: str, route: str) -> None:
    with get_engine().begin() as conn:
        scope_to_principal(conn, subject, role)
        audit_store.append(
            conn,
            actor_kind=role,
            actor_id=subject,
            action="access.denied",
            subject_kind="route",
            subject_ref=route,
            detail={"role": role, "method": method},
        )


def get_denial_recorder() -> Denial:
    return record_denial


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return str(getattr(route, "path", "unknown"))


def _denied(recorder: Denial, request: Request, subject: str | None, role: str) -> HTTPException:
    if subject is not None:
        try:
            recorder(subject, role, request.method, _route_template(request))
        except Exception:  # the answer is still 403; losing the audit entry must be loud
            log.exception("could not audit a denied request")
    return HTTPException(status_code=403, detail="not allowed")


def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
    recorder: Annotated[Denial, Depends(get_denial_recorder)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"})
    try:
        return verifier.verify(credentials.credentials)
    except AuthError as error:
        raise HTTPException(
            401, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"}
        ) from error
    except Forbidden as error:
        raise _denied(recorder, request, error.subject, "none") from error


def require_roles(*roles: Role) -> Callable[..., Principal]:
    """Dependency for a route that only some roles may call."""

    def dependency(
        request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
        recorder: Annotated[Denial, Depends(get_denial_recorder)],
    ) -> Principal:
        try:
            allow(principal, roles)
        except Forbidden as error:
            raise _denied(recorder, request, principal.subject, principal.role.value) from error
        return principal

    return dependency


def get_conn(principal: Annotated[Principal, Depends(current_principal)]) -> Iterator[Connection]:
    """A transaction scoped to the caller. Use with `Depends(get_conn, scope="function")` so it
    commits before the response is sent."""
    with get_engine().begin() as conn:
        scope_to_principal(conn, principal.subject, principal.role.value)
        yield conn
