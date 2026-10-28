"""The model-registry endpoints, with a stand-in registry and no database or MLflow."""

# ruff: noqa: F811  (pytest fixtures imported from test_contract are used as arguments)

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_contract import bearer, client, pems  # noqa: F401

from app.api import deps, models
from app.main import app
from app.ml.gate import Metrics, SignOff, check
from app.ml.registry import AlreadyProduction, NoSuchRelease, ReleaseInfo

GOOD = Metrics(0.74, 0.02, {"gender": 0.03, "region": 0.04})
GAPPY = Metrics(0.74, 0.02, {"gender": 0.03, "region": 0.2})
UNASSESSED = Metrics(0.74, 0.02, {"gender": float("nan")})
WEEKS = {4: "9", 8: "9"}


def info(number: int, metrics: Metrics | None, production: bool = False) -> ReleaseInfo:
    return ReleaseInfo(
        release=number,
        run_id=f"run{number}",
        created_ms=1_700_000_000_000,
        versions=WEEKS,
        metrics=metrics,
        gate=None,
        sign_off=None,
        production=production,
    )


class FakeRegistry:
    def __init__(self, *releases: ReleaseInfo) -> None:
        self.found = {r.release: r for r in releases}
        self.promoted: list[tuple[int, SignOff | None]] = []

    def releases(self) -> list[ReleaseInfo]:
        return sorted(self.found.values(), key=lambda r: r.release, reverse=True)

    def release(self, number: int) -> ReleaseInfo:
        if number not in self.found:
            raise NoSuchRelease(number)
        return self.found[number]

    def card(self, release: ReleaseInfo) -> str:
        return f"# card {release.release}"

    def _current(self) -> Metrics | None:
        return next((r.metrics for r in self.found.values() if r.production), None)

    def assess(self, release: ReleaseInfo, sign_off: SignOff | None = None) -> Any:
        if release.metrics is None:
            raise ValueError("this release has no usable recorded metrics")
        return check(release.metrics, self._current(), sign_off)

    def promote_release(self, release: ReleaseInfo, sign_off: SignOff | None = None) -> Any:
        if release.production:
            raise AlreadyProduction(release.release)
        self.promoted.append((release.release, sign_off))
        return self.assess(release, sign_off)


@pytest.fixture
def registry() -> FakeRegistry:
    return FakeRegistry(info(1, GOOD, production=True), info(2, GAPPY), info(3, UNASSESSED))


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    written: list[dict[str, Any]] = []
    monkeypatch.setattr(models.audit_store, "append", lambda conn, **entry: written.append(entry))
    return written


@pytest.fixture
def api(client: TestClient, registry: FakeRegistry) -> TestClient:
    app.dependency_overrides[deps.get_conn] = lambda: object()
    app.dependency_overrides[models.get_registry] = lambda: registry
    return client


def admin(pems: tuple[str, str]) -> dict[str, str]:
    return bearer(pems, ["admin"])


def test_the_list_shows_every_release_newest_first_with_aggregates_only(
    api: TestClient,
    pems: tuple[str, str],
) -> None:
    reply = api.get("/api/admin/models", headers=admin(pems))
    assert reply.status_code == 200
    body = reply.json()
    assert [r["release"] for r in body] == [3, 2, 1]
    assert [r["in_production"] for r in body] == [False, False, True]
    assert body[1]["gate_now"]["blocks"] == ["gap_high:region"]
    assert body[2]["gate_now"] is None  # the production release is not re-gated
    assert body[0]["metrics"]["recall_gaps"] == {"gender": None}  # NaN becomes null
    assert body[1]["weeks"] == [4, 8]


def test_a_release_without_readable_metrics_is_listed_without_a_verdict(
    api: TestClient,
    registry: FakeRegistry,
    pems: tuple[str, str],
) -> None:
    registry.found[4] = info(4, None)
    body = api.get("/api/admin/models/4", headers=admin(pems)).json()
    assert body["metrics"] is None and body["gate_now"] is None


def test_the_card_comes_back_as_text(api: TestClient, pems: tuple[str, str]) -> None:
    reply = api.get("/api/admin/models/2/card", headers=admin(pems))
    assert reply.json() == {"release": 2, "markdown": "# card 2"}


@pytest.mark.parametrize("path", ["/api/admin/models/99", "/api/admin/models/99/card"])
def test_an_unknown_release_is_a_404(
    api: TestClient,
    pems: tuple[str, str],
    path: str,
) -> None:
    assert api.get(path, headers=admin(pems)).status_code == 404


@pytest.mark.parametrize("release", ["0", "-1", "abc", "1;DROP", "2147483648"])
def test_a_bad_release_number_is_a_422(
    api: TestClient,
    pems: tuple[str, str],
    release: str,
) -> None:
    assert api.get(f"/api/admin/models/{release}", headers=admin(pems)).status_code == 422
    assert (
        api.post(f"/api/admin/models/{release}/promote", json={}, headers=admin(pems)).status_code
        == 422
    )


@pytest.mark.parametrize("limit", ["0", "51", "x"])
def test_bad_paging_on_the_list_is_a_422(
    api: TestClient,
    pems: tuple[str, str],
    limit: str,
) -> None:
    assert api.get(f"/api/admin/models?limit={limit}", headers=admin(pems)).status_code == 422


def test_a_blocked_release_is_refused_without_a_sign_off_and_nothing_changes(
    api: TestClient,
    registry: FakeRegistry,
    audit: list[dict[str, Any]],
    pems: tuple[str, str],
) -> None:
    reply = api.post("/api/admin/models/2/promote", json={}, headers=admin(pems))
    assert reply.status_code == 409
    assert reply.json()["detail"] == {"unresolved": ["gap_high:region"], "hard_failures": []}
    assert registry.promoted == [] and audit == []


def test_a_sign_off_must_list_the_block_it_accepts(
    api: TestClient,
    registry: FakeRegistry,
    audit: list[dict[str, Any]],
    pems: tuple[str, str],
) -> None:
    body = {"reason": "pilot", "covers": ["gap_high:gender"]}
    reply = api.post("/api/admin/models/2/promote", json=body, headers=admin(pems))
    assert reply.status_code == 409 and registry.promoted == [] and audit == []


def test_a_covering_sign_off_promotes_in_the_callers_name_and_is_audited(
    api: TestClient,
    registry: FakeRegistry,
    audit: list[dict[str, Any]],
    pems: tuple[str, str],
) -> None:
    body = {"reason": "pilot only", "covers": ["gap_high:region"]}
    reply = api.post("/api/admin/models/2/promote", json=body, headers=admin(pems))
    assert reply.status_code == 200
    assert reply.json()["overridden"] == ["gap_high:region"]
    assert reply.json()["signed_off_by"] == "u1"
    assert registry.promoted == [(2, SignOff("u1", "pilot only", frozenset({"gap_high:region"})))]
    assert audit == [
        {
            "actor_kind": "admin",
            "actor_id": "u1",
            "action": "model.promoted",
            "subject_kind": "model",
            "subject_ref": "release-2",
            "detail": {"release": 2, "overridden": ["gap_high:region"]},
        }
    ]


def test_missing_numbers_cannot_be_signed_off(
    api: TestClient,
    registry: FakeRegistry,
    audit: list[dict[str, Any]],
    pems: tuple[str, str],
) -> None:
    body = {"reason": "please", "covers": ["unassessed:gender", "gap_high:gender"]}
    reply = api.post("/api/admin/models/3/promote", json=body, headers=admin(pems))
    assert reply.status_code == 409
    assert reply.json()["detail"]["hard_failures"] == ["unassessed:gender"]
    assert registry.promoted == [] and audit == []


def test_a_release_with_no_metrics_is_a_409(
    api: TestClient,
    registry: FakeRegistry,
    pems: tuple[str, str],
) -> None:
    registry.found[4] = info(4, None)
    assert api.post("/api/admin/models/4/promote", json={}, headers=admin(pems)).status_code == 409


def test_the_production_release_cannot_be_promoted_again(
    api: TestClient,
    registry: FakeRegistry,
    pems: tuple[str, str],
) -> None:
    assert api.post("/api/admin/models/1/promote", json={}, headers=admin(pems)).status_code == 409
    assert registry.promoted == []


def test_covers_without_a_reason_are_a_422(
    api: TestClient,
    registry: FakeRegistry,
    pems: tuple[str, str],
) -> None:
    for reason in ("", "   "):
        body = {"reason": reason, "covers": ["gap_high:region"]}
        assert (
            api.post("/api/admin/models/2/promote", json=body, headers=admin(pems)).status_code
            == 422
        )
    assert registry.promoted == []


@pytest.mark.parametrize(
    "body",
    [
        {"covers": ["gap_high:region; DROP TABLE x"]},
        {"covers": ["GAP_HIGH"]},
        {"covers": [""]},
        {"covers": "gap_high:region"},
        {"covers": ["a"] * 21},
        {"reason": "x" * 1001},
        {"actor": "someone-else"},
        {"signed_off_by": "someone-else"},
    ],
)
def test_a_malformed_promotion_request_is_a_422(
    api: TestClient,
    registry: FakeRegistry,
    pems: tuple[str, str],
    body: dict[str, Any],
) -> None:
    reply = api.post("/api/admin/models/2/promote", json=body, headers=admin(pems))
    assert reply.status_code == 422 and registry.promoted == []


def test_if_the_audit_entry_cannot_be_written_nothing_is_promoted(
    api: TestClient,
    registry: FakeRegistry,
    monkeypatch: pytest.MonkeyPatch,
    pems: tuple[str, str],
) -> None:
    def broken(conn: object, **entry: Any) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr(models.audit_store, "append", broken)
    body = {"reason": "pilot", "covers": ["gap_high:region"]}
    with pytest.raises(RuntimeError):
        api.post("/api/admin/models/2/promote", json=body, headers=admin(pems))
    assert registry.promoted == []


def test_only_admins_reach_the_registry(
    api: TestClient,
    registry: FakeRegistry,
    pems: tuple[str, str],
) -> None:
    call: Callable[..., Any] = api.get
    for role in ("mentor", "staff", "faculty"):
        assert call("/api/admin/models", headers=bearer(pems, [role])).status_code == 403
    assert (
        api.post(
            "/api/admin/models/2/promote", json={}, headers=bearer(pems, ["staff"])
        ).status_code
        == 403
    )
    assert registry.promoted == []
