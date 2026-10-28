import base64
import hashlib
import hmac
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.auth import (
    AuthError,
    Forbidden,
    JwksKeys,
    Principal,
    Role,
    StaticKey,
    TokenVerifier,
    allow,
    build_verifier,
    role_from_claims,
)

ISS, AUD = "https://idp.example/realms/college", "risk-api"


def _pem(key: rsa.RSAPrivateKey, private: bool) -> str:
    if private:
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


@pytest.fixture(scope="module")
def keys() -> tuple[str, str, str]:
    """(signing key, matching public key, a stranger's signing key), as PEM text."""
    ours, other = (rsa.generate_private_key(65537, 2048) for _ in range(2))
    return _pem(ours, True), _pem(ours, False), _pem(other, True)


@pytest.fixture
def verifier(keys: tuple[str, str, str]) -> TokenVerifier:
    return TokenVerifier(ISS, AUD, StaticKey(keys[1]))


def claims(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "iss": ISS,
        "aud": AUD,
        "sub": "mentor-17",
        "exp": int(time.time()) + 300,
        "roles": ["mentor"],
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def sign(key: str, payload: dict[str, Any], alg: str = "RS256") -> str:
    return jwt.encode(payload, key, algorithm=alg)


def test_a_good_token_gives_the_subject_and_role(
    verifier: TokenVerifier, keys: tuple[str, str, str]
) -> None:
    assert verifier.verify(sign(keys[0], claims())) == Principal("mentor-17", Role.MENTOR)


def test_a_token_signed_by_someone_else_is_refused(
    verifier: TokenVerifier, keys: tuple[str, str, str]
) -> None:
    with pytest.raises(AuthError):
        verifier.verify(sign(keys[2], claims()))


def test_a_tampered_payload_is_refused(verifier: TokenVerifier, keys: tuple[str, str, str]) -> None:
    head, body, sig = sign(keys[0], claims()).split(".")
    forged = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    forged["roles"] = ["admin"]
    new_body = base64.urlsafe_b64encode(json.dumps(forged).encode()).rstrip(b"=").decode()
    with pytest.raises(AuthError):
        verifier.verify(f"{head}.{new_body}.{sig}")


def test_an_unsigned_token_is_refused(verifier: TokenVerifier) -> None:
    unsigned = jwt.encode(claims(roles=["admin"]), key=None, algorithm="none")  # type: ignore[arg-type]
    with pytest.raises(AuthError):
        verifier.verify(unsigned)


def test_hs256_signed_with_the_public_key_is_refused(
    verifier: TokenVerifier, keys: tuple[str, str, str]
) -> None:
    """The classic key-confusion attack: the public key reused as an HMAC secret."""

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    signing_input = (
        b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        + "."
        + b64(json.dumps(claims(roles=["admin"])).encode())
    )
    mac = hmac.new(keys[1].encode(), signing_input.encode(), hashlib.sha256).digest()
    with pytest.raises(AuthError):
        verifier.verify(f"{signing_input}.{b64(mac)}")


@pytest.mark.parametrize(
    "bad",
    [
        {"exp": int(time.time()) - 3600},
        {"nbf": int(time.time()) + 3600},
        {"iss": "https://evil.example"},
        {"aud": "another-service"},
        {"aud": ["another-service"]},
        {"exp": None},
        {"iss": None},
        {"aud": None},
        {"sub": None},
        {"sub": ""},
        {"sub": "   "},
        {"sub": "m1\nadmin"},
        {"sub": "x" * 256},
        {"sub": 17},
    ],
)
def test_bad_or_missing_claims_are_refused(
    verifier: TokenVerifier, keys: tuple[str, str, str], bad: dict[str, Any]
) -> None:
    with pytest.raises(AuthError):
        verifier.verify(sign(keys[0], claims(**bad)))


def test_a_token_a_few_seconds_past_expiry_is_still_accepted_within_the_leeway(
    verifier: TokenVerifier, keys: tuple[str, str, str]
) -> None:
    assert verifier.verify(sign(keys[0], claims(exp=int(time.time()) - 5))).subject == "mentor-17"


@pytest.mark.parametrize("junk", ["", "abc", "a.b.c", "Bearer x", "\x00"])
def test_junk_is_refused(verifier: TokenVerifier, junk: str) -> None:
    with pytest.raises(AuthError):
        verifier.verify(junk)


def test_an_audience_list_containing_ours_is_accepted(
    verifier: TokenVerifier, keys: tuple[str, str, str]
) -> None:
    assert verifier.verify(sign(keys[0], claims(aud=["other", AUD]))).role is Role.MENTOR


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["mentor"], Role.MENTOR),
        (["faculty"], Role.FACULTY),
        (["staff", "mentor"], Role.STAFF),
        (["mentor", "admin", "faculty"], Role.ADMIN),
        (["offline_access", "mentor"], Role.MENTOR),
        ("mentor", Role.MENTOR),
    ],
)
def test_the_most_privileged_known_role_wins(roles: Any, expected: Role) -> None:
    assert role_from_claims({"roles": roles}, "roles") is expected


@pytest.mark.parametrize(
    "roles", [[], ["student"], ["parent"], ["MENTOR"], ["Mentor "], None, 5, {"mentor": True}]
)
def test_an_account_without_a_known_role_gets_no_access(
    verifier: TokenVerifier, keys: tuple[str, str, str], roles: Any
) -> None:
    with pytest.raises(Forbidden):
        verifier.verify(sign(keys[0], claims(roles=roles)))


def test_a_nested_claim_path_works_for_keycloak_style_tokens(keys: tuple[str, str, str]) -> None:
    keycloak = TokenVerifier(ISS, AUD, StaticKey(keys[1]), roles_claim="realm_access.roles")
    token = sign(keys[0], claims(roles=None, realm_access={"roles": ["staff"]}))
    assert keycloak.verify(token).role is Role.STAFF


def test_allow_checks_the_role_against_the_allowed_set() -> None:
    allow(Principal("a", Role.MENTOR), [Role.MENTOR, Role.STAFF])
    with pytest.raises(Forbidden):
        allow(Principal("a", Role.FACULTY), [Role.MENTOR, Role.STAFF])
    with pytest.raises(Forbidden):
        allow(Principal("a", Role.MENTOR), [])


def test_build_verifier_needs_issuer_audience_and_one_key_source(
    keys: tuple[str, str, str],
) -> None:
    base: dict[str, Any] = {
        "issuer": ISS,
        "audience": AUD,
        "public_key": keys[1],
        "jwks_url": "",
        "roles_claim": "roles",
    }
    assert isinstance(build_verifier(**base).keys, StaticKey)
    for missing in ({"issuer": ""}, {"audience": ""}, {"public_key": "  "}):
        with pytest.raises(ValueError):
            build_verifier(**{**base, **missing})


def test_a_pem_with_escaped_newlines_from_an_env_file_is_repaired(
    keys: tuple[str, str, str],
) -> None:
    flat = keys[1].replace("\n", "\\n")
    verifier = build_verifier(
        issuer=ISS, audience=AUD, public_key=flat, jwks_url="", roles_claim="roles"
    )
    assert verifier.verify(sign(keys[0], claims())).subject == "mentor-17"


def test_a_static_key_wins_over_a_jwks_url(keys: tuple[str, str, str]) -> None:
    def never(url: str) -> Any:
        raise AssertionError("must not fetch JWKS when a static key is set")

    built = build_verifier(
        issuer=ISS,
        audience=AUD,
        public_key=keys[1],
        jwks_url="https://idp.example/jwks",
        roles_claim="roles",
        make_jwks=never,
    )
    assert isinstance(built.keys, StaticKey)


def test_jwks_keys_turn_a_lookup_failure_into_an_auth_error() -> None:
    keys = JwksKeys("http://127.0.0.1:9/never-listening")
    with pytest.raises(AuthError):
        keys.key_for("a.b.c")
