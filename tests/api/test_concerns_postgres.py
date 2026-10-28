"""The concern endpoints against real Postgres (skipped without TEST_DATABASE_URL; CI runs them)."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from test_cases_postgres import (  # noqa: F401
    DAY,
    TEST_DB,
    Api,
    _alembic,
    pems,
)

from app.api import deps
from app.api.concerns import DAILY_LIMIT
from app.core.audit_store import verify
from app.core.auth import StaticKey, TokenVerifier
from app.core.db import get_engine, scope_to_principal
from app.main import app

pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")

ISS, AUD = "https://idp.example", "risk-api"
NOTE = "Missed three labs in a row and seemed distracted"


class Today:
    """The day the API believes it is; tests move it."""

    def __init__(self) -> None:
        self.value = DAY


@pytest.fixture
def clock() -> Today:
    return Today()


@pytest.fixture
def api(
    pems: tuple[str, str],  # noqa: F811
    clock: Today,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Api]:
    """Students 1-2 belong to m1, 3 to m2, and 4 has no mentor."""
    assert TEST_DB is not None
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    get_engine.cache_clear()
    owner = create_engine(TEST_DB)
    with owner.begin() as conn:
        conn.execute(text("INSERT INTO core.terms VALUES (1, 'T', '2026-01-05', '2026-04-19')"))
        conn.execute(text("INSERT INTO core.sections VALUES (1, 'A', 1)"))
        for sid in range(1, 5):
            conn.execute(text("INSERT INTO core.students VALUES (:i, 1)"), {"i": sid})
        for sid, mentor in ((1, "m1"), (2, "m1"), (3, "m2")):
            conn.execute(
                text("INSERT INTO app.mentor_assignments VALUES (:s, :m)"), {"s": sid, "m": mentor}
            )
    verifier = TokenVerifier(ISS, AUD, StaticKey(pems[1]))
    app.dependency_overrides[deps.get_verifier] = lambda: verifier
    app.dependency_overrides[deps.get_today] = lambda: clock.value
    try:
        yield Api(TestClient(app), pems, owner)
    finally:
        app.dependency_overrides.clear()
        get_engine().dispose()
        get_engine.cache_clear()
        owner.dispose()
        _alembic("downgrade", "base")


def raise_concern(
    api: Api, student: int, who: str = "f1", category: str = "attendance", note: str = NOTE
) -> Any:
    return api.client.post(
        "/api/concerns",
        json={"student_id": student, "category": category, "note": note},
        headers=api.auth(who, "faculty"),
    )


def students_seen(api: Api, who: str, role: str, query: str = "") -> list[int]:
    reply = api.get(f"/api/concerns{query}", who, role)
    assert reply.status_code == 200, reply.text
    return sorted(item["student_id"] for item in reply.json()["items"])


def test_faculty_raise_a_concern_and_see_only_their_own(api: Api) -> None:
    reply = raise_concern(api, 1)
    assert reply.status_code == 200 and reply.json() == {"id": 1}
    raise_concern(api, 3, who="f2")
    mine = api.get("/api/concerns", "f1", "faculty").json()
    assert mine["total"] == 1
    assert mine["items"][0] == {
        "id": 1,
        "student_id": 1,
        "category": "attendance",
        "raised_on": "2026-03-02",
        "note": NOTE,
        "acknowledged": False,
        "raised_by": None,  # faculty never see who acknowledged, or the other fields
        "acknowledged_by": None,
        "acknowledged_on": None,
    }
    assert students_seen(api, "f2", "faculty") == [3]
    assert students_seen(api, "f3", "faculty") == []


def test_mentors_see_concerns_about_their_own_mentees_only(api: Api) -> None:
    for student in (1, 2, 3, 4):
        raise_concern(api, student)
    assert students_seen(api, "m1", "mentor") == [1, 2]
    assert students_seen(api, "m2", "mentor") == [3]
    assert students_seen(api, "m3", "mentor") == []
    assert students_seen(api, "boss", "staff") == [1, 2, 3, 4]  # staff also see the unassigned one
    item = api.get("/api/concerns", "m1", "mentor").json()["items"][0]
    assert item["raised_by"] == "f1" and item["note"] == NOTE


def test_admin_and_other_roles_cannot_read_concerns(api: Api) -> None:
    raise_concern(api, 1)
    assert api.get("/api/concerns", "root", "admin").status_code == 403
    assert api.get("/api/concerns", "s1", "student").status_code == 403
    assert api.get("/api/concerns", "p1", "parent").status_code == 403


def test_a_reassigned_student_takes_their_concerns_to_the_new_mentor(api: Api) -> None:
    raise_concern(api, 1)
    with api.owner.begin() as conn:
        conn.execute(
            text("UPDATE app.mentor_assignments SET mentor_id = 'm2' WHERE student_id = 1")
        )
    assert students_seen(api, "m1", "mentor") == []
    assert students_seen(api, "m2", "mentor") == [1]


def test_filters_and_paging(api: Api) -> None:
    for student in (1, 2, 1):
        raise_concern(api, student)
    api.client.post("/api/concerns/1/acknowledge", headers=api.auth("m1", "mentor"))
    assert students_seen(api, "m1", "mentor", "?student_id=1") == [1, 1]
    assert students_seen(api, "m1", "mentor", "?open_only=true") == [1, 2]
    page = api.get("/api/concerns?limit=2&offset=2", "boss", "staff").json()
    assert page["total"] == 3 and len(page["items"]) == 1
    newest_first = api.get("/api/concerns", "boss", "staff").json()["items"]
    assert [i["id"] for i in newest_first] == [3, 2, 1]


def test_an_unknown_student_is_a_404_and_stores_nothing(api: Api) -> None:
    assert raise_concern(api, 999).status_code == 404
    assert api.scalar("SELECT count(*) FROM app.concerns") == 0
    assert raise_concern(api, 1).status_code == 200  # the failed insert left nothing broken


def test_the_note_is_optional_trimmed_and_limited(api: Api) -> None:
    assert raise_concern(api, 1, note="").status_code == 200
    assert raise_concern(api, 1, note="  padded  ").status_code == 200
    assert raise_concern(api, 1, note="x" * 500).status_code == 200
    assert raise_concern(api, 1, note="x" * 501).status_code == 422
    assert raise_concern(api, 1, category="risk").status_code == 422
    notes = api.get("/api/concerns", "boss", "staff").json()["items"]
    assert sorted(len(i["note"]) for i in notes) == [0, 6, 500]


def test_a_faculty_member_has_a_daily_limit_that_resets_and_is_theirs_alone(
    api: Api, clock: Today
) -> None:
    for _ in range(DAILY_LIMIT):
        assert raise_concern(api, 1).status_code == 200
    assert raise_concern(api, 1).status_code == 429
    assert raise_concern(api, 1, who="f2").status_code == 200
    clock.value = DAY + timedelta(days=1)
    assert raise_concern(api, 1).status_code == 200
    assert api.scalar("SELECT count(*) FROM app.concerns") == DAILY_LIMIT + 2


def test_acknowledging_records_who_and_when_once(api: Api, clock: Today) -> None:
    raise_concern(api, 1)
    clock.value = DAY + timedelta(days=2)
    reply = api.client.post("/api/concerns/1/acknowledge", headers=api.auth("m1", "mentor"))
    assert reply.status_code == 200
    body = reply.json()
    assert body["acknowledged"] is True
    assert (body["acknowledged_by"], body["acknowledged_on"]) == ("m1", "2026-03-04")
    again = api.client.post("/api/concerns/1/acknowledge", headers=api.auth("boss", "staff"))
    assert again.status_code == 409
    assert api.scalar("SELECT acknowledged_by FROM app.concerns WHERE id = 1") == "m1"
    assert api.get("/api/concerns", "f1", "faculty").json()["items"][0]["acknowledged"] is True


def test_only_the_right_people_can_acknowledge(api: Api) -> None:
    raise_concern(api, 1)
    raise_concern(api, 4)
    post = api.client.post
    assert post("/api/concerns/1/acknowledge", headers=api.auth("m2", "mentor")).status_code == 404
    assert post("/api/concerns/1/acknowledge", headers=api.auth("f1", "faculty")).status_code == 403
    assert post("/api/concerns/1/acknowledge", headers=api.auth("root", "admin")).status_code == 403
    assert post("/api/concerns/2/acknowledge", headers=api.auth("m1", "mentor")).status_code == 404
    assert (
        post("/api/concerns/999/acknowledge", headers=api.auth("m1", "mentor")).status_code == 404
    )
    assert post("/api/concerns/2/acknowledge", headers=api.auth("boss", "staff")).status_code == 200
    assert api.scalar("SELECT count(*) FROM app.concerns WHERE acknowledged_by IS NOT NULL") == 1


def test_a_concern_opens_no_case_and_no_response_carries_a_band_or_score(api: Api) -> None:
    raise_concern(api, 1)
    bodies = [
        api.get("/api/concerns", who, role).text
        for who, role in (("f1", "faculty"), ("m1", "mentor"), ("boss", "staff"))
    ]
    bodies.append(
        api.client.post("/api/concerns/1/acknowledge", headers=api.auth("m1", "mentor")).text
    )
    for body in bodies:
        for forbidden in ("band", "score", "probab", "state", "case"):
            assert forbidden not in body.lower(), forbidden
    assert api.scalar("SELECT count(*) FROM app.cases") == 0
    assert api.scalar("SELECT count(*) FROM app.risk_scores") == 0


def test_the_audit_log_names_the_concern_and_category_but_never_the_note(api: Api) -> None:
    raise_concern(api, 1, category="wellbeing")
    api.client.post("/api/concerns/1/acknowledge", headers=api.auth("m1", "mentor"))
    with api.owner.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT action, actor_kind, actor_id, subject_ref, detail FROM gov.audit_log "
                "ORDER BY seq"
            )
        ).all()
        assert verify(conn).ok
    assert [(r.action, r.actor_kind, r.actor_id, r.subject_ref) for r in rows] == [
        ("concern.raised", "faculty", "f1", "concern-1"),
        ("concern.acknowledged", "mentor", "m1", "concern-1"),
    ]
    assert all(r.detail == {"category": "wellbeing"} for r in rows)
    assert "labs" not in str(rows)


def test_a_refused_request_leaves_no_audit_entry(api: Api) -> None:
    raise_concern(api, 999)
    api.client.post("/api/concerns/999/acknowledge", headers=api.auth("m1", "mentor"))
    assert api.scalar("SELECT count(*) FROM gov.audit_log WHERE action LIKE 'concern.%'") == 0


@pytest.mark.parametrize(
    ("who", "role", "sql"),
    [
        ("f1", "faculty", "UPDATE app.concerns SET note = 'changed'"),
        ("f1", "faculty", "DELETE FROM app.concerns"),
        (
            "m1",
            "mentor",
            "UPDATE app.concerns SET note = 'changed'",
        ),  # only acknowledgement columns
        ("m1", "mentor", "UPDATE app.concerns SET raised_by = 'someone'"),
        ("boss", "staff", "DELETE FROM app.concerns"),
        (
            "f2",
            "faculty",
            "INSERT INTO app.concerns (student_id, raised_by, raised_on, category) "
            "VALUES (1, 'f1', '2026-03-02', 'other')",
        ),  # in someone else's name
        (
            "m1",
            "mentor",
            "INSERT INTO app.concerns (student_id, raised_by, raised_on, category) "
            "VALUES (1, 'm1', '2026-03-02', 'other')",
        ),  # only faculty raise
    ],
)
def test_the_database_itself_refuses_edits_deletes_and_forged_authors(
    api: Api, who: str, role: str, sql: str
) -> None:
    raise_concern(api, 1)
    with pytest.raises(DBAPIError), get_engine().begin() as conn:
        scope_to_principal(conn, who, role)
        conn.execute(text(sql))
    assert api.scalar("SELECT note FROM app.concerns WHERE id = 1") == NOTE


def test_the_database_refuses_a_half_recorded_acknowledgement(api: Api) -> None:
    raise_concern(api, 1)
    with pytest.raises(DBAPIError), api.owner.begin() as conn:
        conn.execute(text("UPDATE app.concerns SET acknowledged_by = 'm1' WHERE id = 1"))


def test_migration_0010_downgrades_and_upgrades(api: Api) -> None:
    api.owner.dispose()
    get_engine().dispose()
    _alembic("downgrade", "0009")
    _alembic("upgrade", "head")
