"""Auth dependencies through a real FastAPI app, with a local key and a fake audit recorder."""

import time
from collections.abc import Iterator
from typing import Annotated, Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.core.auth import Principal, Role, StaticKey, TokenVerifier

ISS, AUD = "https://idp.example", "risk-api"


@pytest.fixture(scope="module")
def pems() -> tuple[str, str]:
    key = rsa.generate_private_key(65537, 2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


@pytest.fixture
def denials() -> list[tuple[str, str, str, str]]:
    return []


@pytest.fixture
def client(pems: tuple[str, str], denials: list[tuple[str, str, str, str]]) -> Iterator[TestClient]:
    app = FastAPI()

    @app.get("/me")
    def me(who: Annotated[Principal, Depends(deps.current_principal)]) -> dict[str, str]:
        return {"subject": who.subject, "role": who.role.value}

    @app.get("/cases/{case_id}")
    def case(
        case_id: int,
        who: Annotated[Principal, Depends(deps.require_roles(Role.MENTOR, Role.STAFF))],
    ) -> dict[str, int]:
        return {"case": case_id}

    verifier = TokenVerifier(ISS, AUD, StaticKey(pems[1]))
    app.dependency_overrides[deps.get_verifier] = lambda: verifier
    app.dependency_overrides[deps.get_denial_recorder] = lambda: lambda *a: denials.append(a)
    yield TestClient(app)


def token(pems: tuple[str, str], **over: Any) -> dict[str, str]:
    claims: dict[str, Any] = {
        "iss": ISS,
        "aud": AUD,
        "sub": "u1",
        "exp": int(time.time()) + 300,
        "roles": ["mentor"],
    }
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return {"Authorization": "Bearer " + jwt.encode(claims, pems[0], algorithm="RS256")}


def test_a_valid_token_reaches_the_route(client: TestClient, pems: tuple[str, str]) -> None:
    reply = client.get("/me", headers=token(pems))
    assert reply.status_code == 200 and reply.json() == {"subject": "u1", "role": "mentor"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic dXNlcjpwdw=="},
        {"Authorization": "Bearer "},
        {"Authorization": "x"},
    ],
)
def test_no_or_wrong_credentials_are_a_bare_401(
    client: TestClient, headers: dict[str, str]
) -> None:
    reply = client.get("/me", headers=headers)
    assert reply.status_code == 401
    assert reply.headers["www-authenticate"] == "Bearer"
    assert reply.json() == {"detail": "invalid or missing token"}


def test_an_expired_token_is_the_same_bare_401_with_no_reason(
    client: TestClient, pems: tuple[str, str]
) -> None:
    reply = client.get("/me", headers=token(pems, exp=int(time.time()) - 3600))
    assert reply.status_code == 401 and reply.json() == {"detail": "invalid or missing token"}


def test_a_forged_token_is_a_401(client: TestClient) -> None:
    other = rsa.generate_private_key(65537, 2048)
    pem = other.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    forged = jwt.encode(
        {"iss": ISS, "aud": AUD, "sub": "u1", "exp": int(time.time()) + 300, "roles": ["admin"]},
        pem,
        algorithm="RS256",
    )
    assert client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_a_disallowed_role_gets_403_and_the_denial_is_recorded_by_route_template(
    client: TestClient, pems: tuple[str, str], denials: list[tuple[str, str, str, str]]
) -> None:
    reply = client.get("/cases/12", headers=token(pems, roles=["faculty"], sub="f9"))
    assert reply.status_code == 403 and reply.json() == {"detail": "not allowed"}
    assert denials == [("f9", "faculty", "GET", "/cases/{case_id}")]  # not the raw path


def test_an_allowed_role_passes_and_records_nothing(
    client: TestClient, pems: tuple[str, str], denials: list[tuple[str, str, str, str]]
) -> None:
    assert client.get("/cases/12", headers=token(pems, roles=["staff"])).json() == {"case": 12}
    assert denials == []


def test_a_valid_token_without_a_known_role_gets_403_and_is_recorded(
    client: TestClient, pems: tuple[str, str], denials: list[tuple[str, str, str, str]]
) -> None:
    reply = client.get("/me", headers=token(pems, roles=["student"], sub="s1"))
    assert reply.status_code == 403
    assert denials == [("s1", "none", "GET", "/me")]


def test_losing_the_audit_entry_still_answers_403(
    client: TestClient, pems: tuple[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: str) -> None:
        raise RuntimeError("audit database is down")

    client.app.dependency_overrides[deps.get_denial_recorder] = lambda: broken  # type: ignore[attr-defined]
    reply = client.get("/cases/1", headers=token(pems, roles=["faculty"]))
    assert reply.status_code == 403
    assert "could not audit a denied request" in caplog.text


def test_missing_auth_configuration_is_a_503_not_an_open_door(
    pems: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = FastAPI()

    @app.get("/me")
    def me(who: Annotated[Principal, Depends(deps.current_principal)]) -> str:
        return who.subject

    monkeypatch.setenv("JWT_ISSUER", "")
    monkeypatch.setenv("JWT_AUDIENCE", "")
    monkeypatch.chdir("tests")  # keep a developer's .env out of the test
    deps.configured_verifier.cache_clear()
    try:
        reply = TestClient(app).get("/me", headers=token(pems))
    finally:
        deps.configured_verifier.cache_clear()
    assert reply.status_code == 503


def test_a_token_cannot_be_used_before_it_is_valid(
    client: TestClient, pems: tuple[str, str]
) -> None:
    reply = client.get("/me", headers=token(pems, nbf=int(time.time()) + 3600))
    assert reply.status_code == 401
