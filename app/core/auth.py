"""Bearer-token verification and roles. Pure: no web framework, no database.

Only RS256 is accepted, so a token signed with `none`, or with HS256 using the public key as
the secret, is refused before any claim is read. `exp`, `iss`, `aud` and `sub` must be present
and correct. The identity provider decides who has which role; this module only maps the role
names in the token to the roles the API knows. A user with no such role gets no access, and
students and parents have no role at all.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import jwt

ALGORITHMS = ["RS256"]
LEEWAY_SECONDS = 30
MAX_SUBJECT_LENGTH = 255


class Role(StrEnum):
    MENTOR = "mentor"
    STAFF = "staff"  # HoD or counsellor
    FACULTY = "faculty"
    ADMIN = "admin"


# Most privileged first: a token carrying several known roles gets the first one listed here.
PRECEDENCE = (Role.ADMIN, Role.STAFF, Role.MENTOR, Role.FACULTY)


class AuthError(Exception):
    """The token is missing, malformed, expired, or not for this service (HTTP 401)."""


class Forbidden(Exception):
    """The token is valid but its holder may not do this (HTTP 403)."""

    def __init__(self, message: str, subject: str | None = None) -> None:
        super().__init__(message)
        self.subject = subject


@dataclass(frozen=True)
class Principal:
    subject: str
    role: Role


class KeySource(Protocol):
    def key_for(self, token: str) -> Any:
        """The public key that should have signed `token`."""


@dataclass(frozen=True)
class StaticKey:
    pem: str

    def key_for(self, token: str) -> Any:
        return self.pem


class JwksKeys:
    """Keys fetched from an identity provider's JWKS URL (cached by PyJWT's client)."""

    def __init__(self, url: str, lifespan_s: int = 300) -> None:
        self._client = jwt.PyJWKClient(url, cache_keys=True, lifespan=lifespan_s)

    def key_for(self, token: str) -> Any:
        try:
            return self._client.get_signing_key_from_jwt(token).key
        except jwt.PyJWTError as error:
            raise AuthError("no usable signing key for this token") from error


def _dig(claims: Mapping[str, Any], path: str) -> Any:
    """Follow a dotted claim path such as `realm_access.roles`."""
    value: Any = claims
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def role_from_claims(claims: Mapping[str, Any], roles_claim: str) -> Role:
    raw = _dig(claims, roles_claim)
    names = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
    known = {Role(n) for n in names if isinstance(n, str) and n in {r.value for r in Role}}
    for role in PRECEDENCE:
        if role in known:
            return role
    raise Forbidden("this account has no role in this service")


def _clean_subject(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_SUBJECT_LENGTH:
        raise AuthError("token has no usable subject")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise AuthError("token has no usable subject")
    return value


@dataclass(frozen=True)
class TokenVerifier:
    issuer: str
    audience: str
    keys: KeySource
    roles_claim: str = "roles"
    leeway_s: int = LEEWAY_SECONDS

    def verify(self, token: str) -> Principal:
        """Raise `AuthError` for a bad token, `Forbidden` for a good token with no usable role."""
        try:
            claims = jwt.decode(
                token,
                self.keys.key_for(token),
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_s,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as error:
            raise AuthError("invalid token") from error
        subject = _clean_subject(claims.get("sub"))
        try:
            role = role_from_claims(claims, self.roles_claim)
        except Forbidden as error:
            raise Forbidden(str(error), subject) from error
        return Principal(subject, role)


def allow(principal: Principal, roles: Iterable[Role]) -> None:
    if principal.role not in set(roles):
        raise Forbidden(f"role {principal.role.value} may not do this")


def build_verifier(
    *,
    issuer: str,
    audience: str,
    public_key: str,
    jwks_url: str,
    roles_claim: str,
    make_jwks: Callable[[str], KeySource] = JwksKeys,
) -> TokenVerifier:
    """From settings: a static PEM wins if both are set. Raises `ValueError` if neither is."""
    if not issuer or not audience:
        raise ValueError("JWT_ISSUER and JWT_AUDIENCE must be set")
    if public_key.strip():
        keys: KeySource = StaticKey(public_key.replace("\\n", "\n"))
    elif jwks_url.strip():
        keys = make_jwks(jwks_url.strip())
    else:
        raise ValueError("set JWT_PUBLIC_KEY or JWT_JWKS_URL")
    return TokenVerifier(issuer, audience, keys, roles_claim or "roles")
