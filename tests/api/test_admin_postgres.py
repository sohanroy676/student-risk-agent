"""The admin endpoints against real Postgres (skipped without TEST_DATABASE_URL; CI runs them)."""

import json
from typing import Any

import pytest
from sqlalchemy import text
from test_cases_postgres import TEST_DB, Api

from app.core import audit_store

pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")

NEW = "mentor-zz9"


def put(api: Api, student: int, mentor: str, subject: str = "root", role: str = "admin") -> Any:
    return api.client.put(
        f"/api/admin/mentor-assignments/{student}",
        json={"mentor_id": mentor},
        headers=api.auth(subject, role),
    )


def audit_count(api: Api, action: str) -> int:
    return int(api.scalar("SELECT count(*) FROM gov.audit_log WHERE action = :a", a=action))


def case_mentor(api: Api, case_id: int) -> str:
    return str(api.scalar("SELECT mentor_id FROM app.cases WHERE id = :i", i=case_id))


def log_run(api: Api, action: str, detail: dict[str, object]) -> None:
    with api.owner.begin() as conn:
        audit_store.append(
            conn,
            actor_kind="system",
            actor_id=None,
            action=action,
            subject_kind="pipeline",
            subject_ref="2026-03-01",
            detail=detail,
        )


def test_reassigning_moves_the_open_case_and_hides_it_from_the_old_mentor(api: Api) -> None:
    reply = put(api, 1, NEW)
    assert reply.status_code == 200
    assert reply.json() == {"student_id": 1, "changed": True, "cases_moved": 1}
    assert case_mentor(api, 1) == NEW
    assert api.scalar("SELECT mentor_id FROM app.mentor_assignments WHERE student_id = 1") == NEW
    assert api.get("/api/cases/1", "m1", "mentor").status_code == 404
    assert [i["id"] for i in api.get("/api/caseload", "m1", "mentor").json()["items"]] == [3]
    assert [i["id"] for i in api.get("/api/caseload", NEW, "mentor").json()["items"]] == [1]
    kind = "SELECT count(*) FROM app.case_events WHERE case_id = 1 AND kind = 'reassigned'"
    assert api.scalar(kind) == 1
    with api.owner.connect() as conn:
        assert audit_store.verify(conn).ok


def test_the_audit_trail_has_counts_and_case_references_but_no_pairings(api: Api) -> None:
    put(api, 1, NEW)
    assert audit_count(api, "mentor_assignment.set") == 1
    assert audit_count(api, "case.reassigned") == 1
    with api.owner.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT actor_id, subject_ref, detail FROM gov.audit_log "
                "WHERE action IN ('mentor_assignment.set', 'case.reassigned')"
            )
        ).all()
        events = conn.execute(text("SELECT detail FROM app.case_events")).scalars().all()
    for row in rows:
        assert row.actor_id == "root"  # the actor comes from the token
        assert NEW not in json.dumps(row.detail) and "m1" not in json.dumps(row.detail)
        assert row.subject_ref in {"student-1", "case-1"}
    assert NEW not in json.dumps(events)


def test_a_closed_case_keeps_the_mentor_who_handled_it(api: Api) -> None:
    reply = put(api, 5, NEW)
    assert reply.json() == {"student_id": 5, "changed": True, "cases_moved": 0}
    assert case_mentor(api, 4) == "m2"
    assert audit_count(api, "case.reassigned") == 0


def test_repeating_the_same_assignment_changes_and_audits_nothing(api: Api) -> None:
    put(api, 1, NEW)
    before = audit_count(api, "mentor_assignment.set"), audit_count(api, "case.reassigned")
    again = put(api, 1, NEW)
    assert again.json() == {"student_id": 1, "changed": False, "cases_moved": 0}
    assert (
        audit_count(api, "mentor_assignment.set"),
        audit_count(api, "case.reassigned"),
    ) == before


def test_the_same_mentor_still_moves_an_open_case_that_drifted(api: Api) -> None:
    with api.owner.begin() as conn:
        conn.execute(text("INSERT INTO app.mentor_assignments VALUES (1, :m)"), {"m": NEW})
    reply = put(api, 1, NEW)
    assert reply.json() == {"student_id": 1, "changed": False, "cases_moved": 1}
    assert case_mentor(api, 1) == NEW


def test_an_unknown_student_is_a_404_and_leaves_no_trace(api: Api) -> None:
    assert put(api, 999, NEW).status_code == 404
    assert api.scalar("SELECT count(*) FROM app.mentor_assignments") == 0
    assert audit_count(api, "mentor_assignment.set") == 0


@pytest.mark.parametrize("role", ["mentor", "staff", "faculty"])
def test_only_an_admin_can_assign_and_the_refusal_is_audited(api: Api, role: str) -> None:
    assert put(api, 1, NEW, subject="m1", role=role).status_code == 403
    assert case_mentor(api, 1) == "m1"
    assert api.scalar("SELECT count(*) FROM app.mentor_assignments") == 0
    assert audit_count(api, "access.denied") == 1


def test_a_failed_audit_write_rolls_back_the_whole_change(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = audit_store.append

    def fail_on_assignment(conn: Any, **kwargs: Any) -> Any:
        if kwargs["action"] == "mentor_assignment.set":
            raise RuntimeError("audit down")
        return real(conn, **kwargs)

    monkeypatch.setattr(audit_store, "append", fail_on_assignment)
    with pytest.raises(RuntimeError):
        put(api, 1, NEW)
    assert case_mentor(api, 1) == "m1"
    assert api.scalar("SELECT count(*) FROM app.mentor_assignments") == 0
    assert api.scalar("SELECT count(*) FROM app.case_events WHERE kind = 'reassigned'") == 0
    assert audit_count(api, "case.reassigned") == 0


@pytest.mark.parametrize(
    "body",
    [{"mentor_id": ""}, {"mentor_id": "   "}, {"mentor_id": "a\nb"}, {"mentor_id": "x" * 129}]
    + [{}, {"mentor_id": "m", "extra": 1}, {"mentor_id": 5}],
)
def test_bad_bodies_are_422_and_change_nothing(api: Api, body: dict[str, Any]) -> None:
    reply = api.client.put(
        "/api/admin/mentor-assignments/1", json=body, headers=api.auth("root", "admin")
    )
    assert reply.status_code == 422
    assert case_mentor(api, 1) == "m1"


@pytest.mark.parametrize("student", ["0", "-1", "abc", "99999999999"])
def test_bad_student_ids_are_422(api: Api, student: str) -> None:
    reply = api.client.put(
        f"/api/admin/mentor-assignments/{student}",
        json={"mentor_id": NEW},
        headers=api.auth("root", "admin"),
    )
    assert reply.status_code == 422


def test_the_mentor_id_is_trimmed(api: Api) -> None:
    assert put(api, 1, f"  {NEW}  ").status_code == 200
    assert case_mentor(api, 1) == NEW


def test_latest_run_is_a_404_before_any_run(api: Api) -> None:
    assert api.get("/api/admin/nightly/latest", "root", "admin").status_code == 404


def test_latest_run_shows_the_newest_run_with_counts_only(api: Api) -> None:
    log_run(api, "nightly.run", {"as_of": "2026-03-01", "cases_opened": 3, "note": "secret"})
    log_run(api, "case.opened", {"on": "2026-03-02"})
    reply = api.get("/api/admin/nightly/latest", "root", "admin")
    body = reply.json()
    assert reply.status_code == 200 and body["action"] == "nightly.run"
    assert body["detail"] == {"as_of": "2026-03-01", "cases_opened": 3}
    log_run(api, "nightly.halted", {"cause": "data_quality_failed"})
    body = api.get("/api/admin/nightly/latest", "root", "admin").json()
    assert body["action"] == "nightly.halted" and body["detail"] == {"cause": "data_quality_failed"}


def test_the_audit_check_passes_on_an_intact_log_and_reports_the_head(api: Api) -> None:
    log_run(api, "nightly.run", {"as_of": "2026-03-01"})
    body = api.get("/api/admin/audit/verify", "root", "admin").json()
    assert body["ok"] is True and body["checked"] == 1 and body["problem"] is None
    again = api.get(f"/api/admin/audit/verify?anchor={body['anchor']}", "root", "admin").json()
    assert again["ok"] is True


def test_the_audit_check_on_an_empty_log(api: Api) -> None:
    body = api.get("/api/admin/audit/verify", "root", "admin").json()
    assert body == {
        "ok": True,
        "checked": 0,
        "first_bad_seq": None,
        "problem": None,
        "anchor": None,
    }


def test_the_audit_check_catches_a_rewritten_row(api: Api) -> None:
    log_run(api, "nightly.run", {"as_of": "2026-03-01"})
    log_run(api, "nightly.run", {"as_of": "2026-03-02"})
    with api.owner.begin() as conn:
        conn.execute(text("ALTER TABLE gov.audit_log DISABLE TRIGGER USER"))
        conn.execute(text("UPDATE gov.audit_log SET subject_ref = 'x' WHERE seq = 1"))
        conn.execute(text("ALTER TABLE gov.audit_log ENABLE TRIGGER USER"))
    body = api.get("/api/admin/audit/verify", "root", "admin").json()
    assert body["ok"] is False and body["first_bad_seq"] == 1 and body["problem"]


def test_the_audit_check_catches_cut_off_rows_only_with_an_anchor(api: Api) -> None:
    log_run(api, "nightly.run", {"as_of": "2026-03-01"})
    log_run(api, "nightly.run", {"as_of": "2026-03-02"})
    anchor = api.get("/api/admin/audit/verify", "root", "admin").json()["anchor"]
    with api.owner.begin() as conn:
        conn.execute(text("ALTER TABLE gov.audit_log DISABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM gov.audit_log WHERE seq = 2"))
        conn.execute(text("ALTER TABLE gov.audit_log ENABLE TRIGGER USER"))
    assert api.get("/api/admin/audit/verify", "root", "admin").json()["ok"] is True
    cut = api.get(f"/api/admin/audit/verify?anchor={anchor}", "root", "admin").json()
    assert cut["ok"] is False and cut["problem"]


@pytest.mark.parametrize("anchor", ["nonsense", "1:abc", "0:" + "a" * 64, "1:" + "A" * 64, ""])
def test_a_malformed_anchor_is_422(api: Api, anchor: str) -> None:
    reply = api.get(f"/api/admin/audit/verify?anchor={anchor}", "root", "admin")
    assert reply.status_code == 422


@pytest.mark.parametrize("role", ["mentor", "staff"])
@pytest.mark.parametrize("path", ["/api/admin/nightly/latest", "/api/admin/audit/verify"])
def test_only_an_admin_can_read_the_run_and_the_audit_check(api: Api, role: str, path: str) -> None:
    log_run(api, "nightly.run", {"as_of": "2026-03-01"})
    assert api.get(path, "m1", role).status_code == 403
