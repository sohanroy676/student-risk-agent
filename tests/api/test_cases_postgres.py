"""The case endpoints against real Postgres (skipped without TEST_DATABASE_URL; CI runs them)."""

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import date
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from app.api import deps
from app.core.audit_store import verify
from app.core.auth import StaticKey, TokenVerifier
from app.core.db import get_engine, scope_to_principal
from app.main import app

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")

ISS, AUD = "https://idp.example", "risk-api"
DAY = date(2026, 3, 2)


def _alembic(*args: str) -> None:
    assert TEST_DB is not None
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": TEST_DB},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr


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


SEED_CASES = (
    # id, student, mentor, state, due_on, closed_on
    (1, 1, "m1", "drafted", "2026-03-05", None),
    (2, 4, "m2", "new", "2026-03-03", None),
    (3, 2, "m1", "in_review", "2026-03-04", None),
    (4, 5, "m2", "resolved", None, "2026-03-01"),
)


class Api:
    def __init__(self, client: TestClient, pems: tuple[str, str], owner: Engine) -> None:
        self.client, self.pems, self.owner = client, pems, owner

    def auth(self, subject: str, role: str) -> dict[str, str]:
        claims = {
            "iss": ISS,
            "aud": AUD,
            "sub": subject,
            "exp": int(time.time()) + 600,
            "roles": [role],
        }
        return {"Authorization": "Bearer " + jwt.encode(claims, self.pems[0], algorithm="RS256")}

    def get(self, path: str, subject: str, role: str) -> Any:
        return self.client.get(path, headers=self.auth(subject, role))

    def act(self, case_id: int, action: str, subject: str, role: str) -> Any:
        return self.client.post(
            f"/api/cases/{case_id}/actions",
            json={"action": action},
            headers=self.auth(subject, role),
        )

    def scalar(self, sql: str, **params: object) -> Any:
        with self.owner.connect() as conn:
            return conn.execute(text(sql), params).scalar()


@pytest.fixture
def api(pems: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    assert TEST_DB is not None
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    get_engine.cache_clear()
    owner = create_engine(TEST_DB)
    with owner.begin() as conn:
        conn.execute(text("INSERT INTO core.terms VALUES (1, 'T', '2026-01-05', '2026-04-19')"))
        conn.execute(text("INSERT INTO core.sections VALUES (1, 'A', 1)"))
        for sid in range(1, 7):
            conn.execute(text("INSERT INTO core.students VALUES (:i, 1)"), {"i": sid})
        for case_id, student, mentor, state, due, closed in SEED_CASES:
            conn.execute(
                text(
                    "INSERT INTO app.cases (id, student_id, mentor_id, state, band, probability, "
                    "reason, opened_on, entered_on, due_on, closed_on) VALUES (:id, :s, :m, :st, "
                    "'red', 0.93, 'red', '2026-03-01', '2026-03-01', CAST(:due AS date), "
                    "CAST(:closed AS date))"
                ),
                {
                    "id": case_id,
                    "s": student,
                    "m": mentor,
                    "st": state,
                    "due": due,
                    "closed": closed,
                },
            )
        # an event whose stored detail carries things a client must never see
        conn.execute(
            text(
                "INSERT INTO app.case_events "
                "(case_id, on_date, kind, actor_kind, to_state, detail) "
                "VALUES (1, '2026-03-01', 'opened', 'system', 'new', "
                'CAST(\'{"reason": "red", "probability": 0.93, "student_name": "X"}\' '
                "AS jsonb)), (1, '2026-03-02', 'save_plan', 'agent', 'drafted', '{}'::jsonb), "
                "(2, '2026-03-01', 'opened', 'system', 'new', '{}'::jsonb)"
            )
        )
        for case_id in (1, 2):
            conn.execute(
                text(
                    "INSERT INTO app.case_reasons VALUES (:c, '2026-03-02', 1, :f, "
                    "'attendance_rate', 0.4, 'attendance is 40% so far')"
                ),
                {"c": case_id, "f": f"case-{case_id}/attendance_rate/2026-03-02"},
            )
    verifier = TokenVerifier(ISS, AUD, StaticKey(pems[1]))
    app.dependency_overrides[deps.get_verifier] = lambda: verifier
    app.dependency_overrides[deps.get_today] = lambda: DAY
    try:
        yield Api(TestClient(app), pems, owner)
    finally:
        app.dependency_overrides.clear()
        get_engine().dispose()
        get_engine.cache_clear()
        owner.dispose()
        _alembic("downgrade", "base")


def ids(reply: Any) -> list[int]:
    assert reply.status_code == 200, reply.text
    return [item["id"] for item in reply.json()["items"]]


def test_a_mentor_sees_only_their_own_open_cases_most_urgent_first(api: Api) -> None:
    assert ids(api.get("/api/caseload", "m1", "mentor")) == [3, 1]  # due 03-04 then 03-05
    assert ids(api.get("/api/caseload", "m2", "mentor")) == [2]  # the resolved one is closed


def test_closed_cases_appear_only_when_asked_for(api: Api) -> None:
    assert ids(api.get("/api/caseload?include_closed=true", "m2", "mentor")) == [2, 4]
    assert ids(api.get("/api/caseload?state=resolved", "m2", "mentor")) == [4]
    assert ids(api.get("/api/caseload?state=resolved", "m1", "mentor")) == []


@pytest.mark.parametrize("role", ["staff", "admin"])
def test_staff_and_admin_see_every_open_case_and_can_filter_by_mentor(api: Api, role: str) -> None:
    assert ids(api.get("/api/caseload", "boss", role)) == [2, 3, 1]
    assert ids(api.get("/api/caseload?mentor=m2", "boss", role)) == [2]


def test_a_mentor_asking_for_another_mentors_cases_gets_nothing(api: Api) -> None:
    assert ids(api.get("/api/caseload?mentor=m2", "m1", "mentor")) == []


def test_paging_reports_the_total_and_stays_in_order(api: Api) -> None:
    first = api.get("/api/caseload?limit=2", "boss", "staff").json()
    rest = api.get("/api/caseload?limit=2&offset=2", "boss", "staff").json()
    assert [i["id"] for i in first["items"]] == [2, 3] and first["total"] == 3
    assert [i["id"] for i in rest["items"]] == [1] and (rest["offset"], rest["limit"]) == (2, 2)
    assert api.get("/api/caseload?offset=50", "boss", "staff").json()["items"] == []


def test_no_response_carries_a_probability_a_score_or_a_stored_secret(api: Api) -> None:
    bodies = [
        api.get("/api/caseload?include_closed=true", "boss", "staff").text,
        api.get("/api/cases/1", "m1", "mentor").text,
        api.get("/api/cases/1", "boss", "staff").text,
        api.get("/api/cases/1", "root", "admin").text,
    ]
    for body in bodies:
        for forbidden in ("probab", "score", "0.93", "student_name"):
            assert forbidden not in body.lower(), forbidden
    assert '"band":"red"' in bodies[0].replace(" ", "")  # the band is what mentors do see


def test_case_detail_shows_the_timeline_and_the_reasons_to_the_mentor(api: Api) -> None:
    body = api.get("/api/cases/1", "m1", "mentor").json()
    assert [e["kind"] for e in body["timeline"]] == ["opened", "save_plan"]
    assert body["timeline"][0]["detail"] == {"reason": "red"}  # only the allow-listed keys
    assert body["reasons"] == [
        {
            "rank": 1,
            "fact_id": "case-1/attendance_rate/2026-03-02",
            "feature": "attendance_rate",
            "text": "attendance is 40% so far",
        }
    ]
    assert body["state"] == "drafted" and body["approved_by"] is None


def test_staff_see_reasons_but_admin_does_not(api: Api) -> None:
    assert len(api.get("/api/cases/1", "boss", "staff").json()["reasons"]) == 1
    assert api.get("/api/cases/1", "root", "admin").json()["reasons"] == []


def test_a_hidden_case_and_a_missing_case_look_exactly_alike(api: Api) -> None:
    hidden = api.get("/api/cases/2", "m1", "mentor")  # m2's case
    missing = api.get("/api/cases/999", "m1", "mentor")
    assert (hidden.status_code, hidden.json()) == (missing.status_code, missing.json())
    assert hidden.status_code == 404


def test_denied_roles_get_403_and_the_denial_is_audited_without_touching_cases(api: Api) -> None:
    reply = api.get("/api/cases/1", "f1", "faculty")
    assert reply.status_code == 403
    row = api.scalar(
        "SELECT detail FROM gov.audit_log WHERE action = 'access.denied' AND actor_id = 'f1'"
    )
    assert row == {"role": "faculty", "method": "GET"}
    assert api.scalar("SELECT subject_ref FROM gov.audit_log WHERE actor_id = 'f1'") == (
        "/api/cases/{case_id}"
    )


def test_a_mentor_approves_their_own_drafted_case_and_it_is_recorded_everywhere(api: Api) -> None:
    reply = api.act(1, "approve", "m1", "mentor")
    assert reply.status_code == 200 and reply.json() == {"id": 1, "state": "monitoring"}
    detail = api.get("/api/cases/1", "m1", "mentor").json()
    assert (detail["approved_by"], detail["approved_on"]) == ("m1", "2026-03-02")
    assert detail["timeline"][-1]["kind"] == "approve"
    audited = api.scalar(
        "SELECT concat_ws('|', actor_kind, actor_id, subject_ref) FROM gov.audit_log "
        "WHERE action = 'case.approve'"
    )
    assert audited == "mentor|m1|case-1"
    with api.owner.connect() as conn:
        assert verify(conn).ok


def test_the_actor_is_the_caller_whatever_the_request_claims(api: Api) -> None:
    reply = api.client.post(
        "/api/cases/1/actions",
        json={"action": "approve", "actor": "mentor", "actor_id": "m1"},
        headers=api.auth("boss", "staff"),
    )
    assert reply.status_code == 422
    assert api.act(1, "approve", "boss", "staff").status_code == 403


def test_a_wrong_role_is_403_and_audited_while_a_wrong_state_is_409(api: Api) -> None:
    refused = api.act(1, "approve", "boss", "staff")  # only a mentor approves
    assert refused.status_code == 403
    assert api.scalar("SELECT count(*) FROM gov.audit_log WHERE actor_id = 'boss'") == 1
    wrong_state = api.act(3, "approve", "m1", "mentor")  # in review, not drafted
    assert wrong_state.status_code == 409 and "cannot approve" in wrong_state.json()["detail"]
    assert api.scalar("SELECT state FROM app.cases WHERE id = 1") == "drafted"
    assert api.scalar("SELECT approved_by FROM app.cases WHERE id = 1") is None
    assert api.scalar("SELECT count(*) FROM app.case_events WHERE case_id IN (1, 3)") == 2


def test_approving_twice_is_refused_the_second_time(api: Api) -> None:
    assert api.act(1, "approve", "m1", "mentor").status_code == 200
    assert api.act(1, "approve", "m1", "mentor").status_code == 409


def test_a_mentor_cannot_act_on_someone_elses_case(api: Api) -> None:
    reply = api.act(2, "dismiss", "m1", "mentor")
    assert reply.status_code == 404
    assert api.scalar("SELECT state FROM app.cases WHERE id = 2") == "new"


def test_staff_can_dismiss_any_case_and_admin_can_act_on_none(api: Api) -> None:
    assert api.act(2, "dismiss", "root", "admin").status_code == 403
    assert api.act(2, "dismiss", "boss", "staff").json() == {"id": 2, "state": "dismissed"}
    assert api.scalar("SELECT closed_on FROM app.cases WHERE id = 2") == DAY


def test_actions_the_api_does_not_offer_cannot_be_reached(api: Api) -> None:
    for action in ("save_plan", "followup_due", "approve!"):
        assert api.act(1, action, "m1", "mentor").status_code == 422
    assert api.scalar("SELECT state FROM app.cases WHERE id = 1") == "drafted"


def test_the_api_cannot_reach_data_the_role_has_no_grant_on(api: Api) -> None:
    with get_engine().begin() as conn:
        scope_to_principal(conn, "root", "admin")
        with pytest.raises(DBAPIError, match="permission denied"):
            conn.execute(text("SELECT * FROM app.risk_scores"))


def test_p95_latency_stays_under_half_a_second_with_a_thousand_cases(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    with api.owner.begin() as conn:
        conn.execute(
            text("INSERT INTO core.students SELECT g, 1 FROM generate_series(1000, 5999) g")
        )
        conn.execute(
            text(
                "INSERT INTO app.cases (id, student_id, mentor_id, state, band, probability, "
                "reason, opened_on, entered_on, due_on) SELECT g, g, 'm' || (g % 20), 'new', "
                "'red', 0.9, 'red', '2026-03-01', '2026-03-01', DATE '2026-03-02' + (g % 30) "
                "FROM generate_series(1000, 1999) g"
            )
        )
        conn.execute(
            text(
                "INSERT INTO app.case_reasons SELECT g, '2026-03-02', 1, 'case-' || g, 'f', 1, 't' "
                "FROM generate_series(1000, 1999) g"
            )
        )
    timings: list[float] = []
    for i in range(240):
        mentor = f"m{i % 20}"
        kind = i % 3
        started = time.perf_counter()
        if kind == 0:
            reply = api.get("/api/caseload", mentor, "mentor")
        elif kind == 1:
            reply = api.get("/api/caseload?limit=50", "boss", "staff")
        else:
            reply = api.get(f"/api/cases/{1000 + i % 20}", mentor, "mentor")
        timings.append(time.perf_counter() - started)
        assert reply.status_code == 200, reply.text
    timings.sort()
    p50, p95 = timings[len(timings) // 2], timings[int(len(timings) * 0.95) - 1]
    with capsys.disabled():
        print(f"\nAPI over 1,000 cases: p50 {p50 * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms")
    assert p95 < 0.5, f"p95 was {p95 * 1000:.0f} ms"
