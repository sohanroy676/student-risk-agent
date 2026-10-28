"""Properties of the API surface that must hold whatever the routes do (no database needed)."""

import re
import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api import cases, deps
from app.core.auth import Principal, Role, StaticKey, TokenVerifier
from app.main import app

ISS, AUD = "https://idp.example", "risk-api"
LEAKY = re.compile(r"probab|score|risk", re.IGNORECASE)
ROUTERS = (cases.router,)  # add each new router here; the guard test below fails if one is missed
API_ROUTES = [r for router in ROUTERS for r in router.routes if isinstance(r, APIRoute)]


def _walk(dependant: Dependant) -> Iterator[Any]:
    for sub in dependant.dependencies:
        yield sub.call
        yield from _walk(sub)


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def _body(route: APIRoute) -> dict[str, str] | None:
    return {"action": "dismiss"} if "POST" in route.methods else None


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
def client(pems: tuple[str, str]) -> Iterator[TestClient]:
    """The real app, a local signing key, and a database dependency that must never be used."""
    verifier = TokenVerifier(ISS, AUD, StaticKey(pems[1]))

    def no_database() -> Iterator[None]:
        raise AssertionError("a request that should have been refused opened the database")
        yield  # pragma: no cover

    app.dependency_overrides[deps.get_verifier] = lambda: verifier
    app.dependency_overrides[deps.get_conn] = no_database
    app.dependency_overrides[deps.get_denial_recorder] = lambda: lambda *a: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def bearer(pems: tuple[str, str], roles: list[str]) -> dict[str, str]:
    claims = {"iss": ISS, "aud": AUD, "sub": "u1", "exp": int(time.time()) + 300, "roles": roles}
    return {"Authorization": "Bearer " + jwt.encode(claims, pems[0], algorithm="RS256")}


def test_there_are_api_routes_to_check() -> None:
    assert {r.path for r in API_ROUTES} >= {
        "/api/caseload",
        "/api/cases/{case_id}",
        "/api/cases/{case_id}/actions",
    }


def test_the_routes_checked_here_are_exactly_the_routes_the_app_serves() -> None:
    """A router added to the app but not to ROUTERS would escape every test below."""
    served = {
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        if path.startswith("/api")
        for method in methods
    }
    checked = {(m, r.path) for r in API_ROUTES for m in r.methods}
    assert served == checked


@pytest.mark.parametrize("route", API_ROUTES, ids=lambda r: f"{sorted(r.methods)}{r.path}")
def test_every_api_route_requires_a_verified_caller(route: APIRoute) -> None:
    assert deps.current_principal in set(_walk(route.dependant))


@pytest.mark.parametrize("route", API_ROUTES, ids=lambda r: f"{sorted(r.methods)}{r.path}")
def test_without_a_token_every_api_route_is_a_401(client: TestClient, route: APIRoute) -> None:
    method = next(iter(route.methods))
    reply = client.request(method, _concrete(route.path), json=_body(route))
    assert reply.status_code == 401 and reply.json() == {"detail": "invalid or missing token"}


@pytest.mark.parametrize("route", API_ROUTES, ids=lambda r: f"{sorted(r.methods)}{r.path}")
@pytest.mark.parametrize("roles", [["faculty"], ["student"], ["parent"], []])
def test_faculty_students_and_parents_get_403_everywhere_before_any_data_is_read(
    client: TestClient, pems: tuple[str, str], route: APIRoute, roles: list[str]
) -> None:
    method = next(iter(route.methods))
    reply = client.request(
        method, _concrete(route.path), json=_body(route), headers=bearer(pems, roles)
    )
    assert reply.status_code == 403 and reply.json() == {"detail": "not allowed"}


def test_an_admin_can_read_but_not_act_on_cases(client: TestClient, pems: tuple[str, str]) -> None:
    reply = client.post(
        "/api/cases/1/actions", json={"action": "dismiss"}, headers=bearer(pems, ["admin"])
    )
    assert reply.status_code == 403


def test_no_response_model_exposes_a_probability_or_score_and_band_stays_in_case_models() -> None:
    schemas = app.openapi()["components"]["schemas"]
    for name, schema in schemas.items():
        for prop in schema.get("properties", {}):
            assert not LEAKY.search(prop), f"{name}.{prop} looks like a score field"
            if prop == "band":
                assert name in {"CaseSummary", "CaseDetail"}, f"{name} exposes band"


def test_only_roles_that_may_see_the_band_can_read_cases() -> None:
    assert set(cases.CASE_READERS) == {Role.MENTOR, Role.STAFF, Role.ADMIN}
    assert Role.FACULTY not in cases.CASE_READERS
    assert Role.FACULTY not in cases.REASON_READERS and Role.ADMIN not in cases.REASON_READERS


def test_the_actor_on_an_action_never_comes_from_the_request() -> None:
    schema = app.openapi()["components"]["schemas"]["ActionRequest"]
    assert set(schema["properties"]) == {"action"} and schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"action": "save_plan"},  # the agent's move
        {"action": "followup_due"},  # the timer's move
        {"action": "APPROVE"},
        {"action": ""},
        {"action": "dismiss", "actor": "staff"},
        {"action": "dismiss", "actor_id": "someone-else"},
        {},
        {"action": ["dismiss"]},
    ],
)
def test_an_action_request_accepts_only_the_five_human_actions(
    client: TestClient, pems: tuple[str, str], body: dict[str, Any]
) -> None:
    app.dependency_overrides[deps.get_conn] = lambda: None
    reply = client.post("/api/cases/1/actions", json=body, headers=bearer(pems, ["mentor"]))
    assert reply.status_code == 422


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=201", "limit=-1", "limit=abc", "offset=-1", "offset=100001", "state=bogus"],
)
def test_bad_paging_or_filters_are_a_422(
    client: TestClient, pems: tuple[str, str], query: str
) -> None:
    app.dependency_overrides[deps.get_conn] = lambda: None
    reply = client.get(f"/api/caseload?{query}", headers=bearer(pems, ["mentor"]))
    assert reply.status_code == 422


def test_a_case_id_that_is_not_a_number_is_a_422_not_an_error(
    client: TestClient, pems: tuple[str, str]
) -> None:
    app.dependency_overrides[deps.get_conn] = lambda: None
    assert client.get("/api/cases/abc", headers=bearer(pems, ["mentor"])).status_code == 422
    assert (
        client.get("/api/cases/1; DROP TABLE x", headers=bearer(pems, ["mentor"])).status_code
        == 422
    )


def test_principal_roles_in_the_contract_match_the_real_roles() -> None:
    assert set(cases.CASE_ACTORS) == {Role.MENTOR, Role.STAFF}
    assert isinstance(Principal("a", Role.MENTOR), Principal)
