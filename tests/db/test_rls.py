"""Row-level security and grants for the API role, against real Postgres (CI runs these)."""

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from app.cases.states import Action, Actor
from app.cases.store import advance
from app.core.audit_store import append, verify
from app.core.db import scope_to_principal

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(TEST_DB is None, reason="TEST_DATABASE_URL not set")

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


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Students 1-3 belong to m1 and 4-6 to m2; one open case each for students 1 and 4."""
    assert TEST_DB is not None
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    eng = create_engine(TEST_DB, pool_size=1, max_overflow=0)
    try:
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO core.terms VALUES (1, 'T', '2026-01-05', '2026-04-19')"))
            conn.execute(text("INSERT INTO core.sections VALUES (1, 'A', 1)"))
            for sid in range(1, 7):
                conn.execute(text("INSERT INTO core.students VALUES (:i, 1)"), {"i": sid})
                conn.execute(
                    text("INSERT INTO app.mentor_assignments VALUES (:i, :m)"),
                    {"i": sid, "m": "m1" if sid <= 3 else "m2"},
                )
            conn.execute(
                text("INSERT INTO restricted.student_attributes VALUES (1, 'F', 'general')")
            )
            conn.execute(text("INSERT INTO app.risk_scores VALUES (1, '2026-03-02', 0.9, 'red')"))
            for case_id, student, mentor in ((1, 1, "m1"), (2, 4, "m2")):
                conn.execute(
                    text(
                        "INSERT INTO app.cases (id, student_id, mentor_id, state, band, "
                        "probability, reason, opened_on, entered_on, due_on) "
                        "VALUES (:id, :s, :m, 'new', 'red', 0.9, 'red', "
                        "'2026-03-02', '2026-03-02', '2026-03-03')"
                    ),
                    {"id": case_id, "s": student, "m": mentor},
                )
                conn.execute(
                    text(
                        "INSERT INTO app.case_events (case_id, on_date, kind, actor_kind) "
                        "VALUES (:c, '2026-03-02', 'opened', 'system')"
                    ),
                    {"c": case_id},
                )
                conn.execute(
                    text(
                        "INSERT INTO app.case_reasons VALUES (:c, '2026-03-02', 1, :f, "
                        "'attendance_rate', 0.4, 'attendance 40%')"
                    ),
                    {"c": case_id, "f": f"case-{case_id}/attendance_rate/2026-03-02"},
                )
        yield eng
    finally:
        eng.dispose()
        _alembic("downgrade", "base")


@contextmanager
def as_user(engine: Engine, subject: str, role: str) -> Iterator[Connection]:
    with engine.begin() as conn:
        scope_to_principal(conn, subject, role)
        yield conn


def ids(conn: Connection, sql: str) -> list[int]:
    return [int(v) for v in conn.execute(text(sql)).scalars()]


CASES = "SELECT id FROM app.cases ORDER BY id"
EVENTS = "SELECT case_id FROM app.case_events ORDER BY case_id"
REASONS = "SELECT case_id FROM app.case_reasons ORDER BY case_id"
ASSIGNED = "SELECT student_id FROM app.mentor_assignments ORDER BY student_id"


def test_a_mentor_sees_only_their_own_mentees_rows(engine: Engine) -> None:
    with as_user(engine, "m1", "mentor") as conn:
        assert ids(conn, CASES) == [1]
        assert ids(conn, EVENTS) == [1]
        assert ids(conn, REASONS) == [1]
        assert ids(conn, ASSIGNED) == [1, 2, 3]
    with as_user(engine, "m2", "mentor") as conn:
        assert ids(conn, CASES) == [2]
        assert ids(conn, ASSIGNED) == [4, 5, 6]


@pytest.mark.parametrize("role", ["staff", "admin"])
def test_oversight_roles_see_every_case(engine: Engine, role: str) -> None:
    with as_user(engine, "boss", role) as conn:
        assert ids(conn, CASES) == [1, 2]
        assert ids(conn, EVENTS) == [1, 2]
        assert ids(conn, REASONS) == [1, 2]
        assert ids(conn, ASSIGNED) == [1, 2, 3, 4, 5, 6]


def test_faculty_see_no_case_rows_at_all(engine: Engine) -> None:
    with as_user(engine, "f1", "faculty") as conn:
        for sql in (CASES, EVENTS, REASONS, ASSIGNED):
            assert ids(conn, sql) == []


@pytest.mark.parametrize(
    ("subject", "role"), [("", "mentor"), ("m1", ""), ("m1", "hacker"), ("m1", "MENTOR"), ("", "")]
)
def test_missing_or_unknown_identity_sees_nothing(engine: Engine, subject: str, role: str) -> None:
    with as_user(engine, subject, role) as conn:
        assert ids(conn, CASES) == []
        assert ids(conn, ASSIGNED) == []


def test_a_request_that_was_never_scoped_sees_nothing(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE app_api_role"))
        assert ids(conn, CASES) == []


def test_a_mentor_cannot_change_a_case_that_is_not_theirs(engine: Engine) -> None:
    with as_user(engine, "m1", "mentor") as conn:
        own = conn.execute(text("UPDATE app.cases SET state = 'drafted' WHERE id = 1"))
        other = conn.execute(text("UPDATE app.cases SET state = 'drafted' WHERE id = 2"))
        assert (own.rowcount, other.rowcount) == (1, 0)


def test_a_mentor_cannot_hand_their_case_to_someone_else(engine: Engine) -> None:
    with (
        pytest.raises(DBAPIError, match="row-level security"),
        as_user(engine, "m1", "mentor") as conn,
    ):
        conn.execute(text("UPDATE app.cases SET mentor_id = 'm2' WHERE id = 1"))


def test_a_mentor_cannot_write_events_on_another_mentors_case(engine: Engine) -> None:
    insert = text(
        "INSERT INTO app.case_events (case_id, on_date, kind, actor_kind) "
        "VALUES (:c, '2026-03-02', 'note', 'mentor')"
    )
    with as_user(engine, "m1", "mentor") as conn:
        conn.execute(insert, {"c": 1})
    with (
        pytest.raises(DBAPIError, match="row-level security"),
        as_user(engine, "m1", "mentor") as conn,
    ):
        conn.execute(insert, {"c": 2})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM app.risk_scores",
        "SELECT * FROM core.students",
        "SELECT * FROM restricted.student_attributes",
        "SELECT * FROM raw.students",
        "SELECT * FROM raw.dq_reports",
        "SELECT * FROM core.marks",
    ],
)
def test_the_api_role_cannot_read_scores_students_or_protected_data(
    engine: Engine, sql: str
) -> None:
    for role in ("mentor", "staff", "admin"):
        with (
            pytest.raises(DBAPIError, match="permission denied"),
            as_user(engine, "x", role) as conn,
        ):
            conn.execute(text(sql))


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO app.cases (student_id, mentor_id, state, band, probability, reason, "
        "opened_on, entered_on) VALUES (2, 'm1', 'new', 'red', 0.9, 'red', '2026-03-02', "
        "'2026-03-02')",
        "DELETE FROM app.cases",
        "DELETE FROM app.case_events",
        "UPDATE app.case_events SET kind = 'x'",
        "UPDATE app.case_reasons SET text = 'x'",
        "INSERT INTO app.case_reasons VALUES (1, '2026-03-03', 1, 'f', 'a', 1, 't')",
        "INSERT INTO app.mentor_assignments VALUES (99, 'm1')",
    ],
)
def test_the_api_role_cannot_do_writes_it_was_not_given(engine: Engine, sql: str) -> None:
    with pytest.raises(DBAPIError), as_user(engine, "boss", "staff") as conn:
        conn.execute(text(sql))


def test_only_an_admin_can_change_mentor_assignments(engine: Engine) -> None:
    with as_user(engine, "boss", "staff") as conn:
        assert (
            conn.execute(text("UPDATE app.mentor_assignments SET mentor_id = 'm9'")).rowcount == 0
        )
    with as_user(engine, "root", "admin") as conn:
        assert (
            conn.execute(
                text("UPDATE app.mentor_assignments SET mentor_id = 'm3' WHERE student_id = 1")
            ).rowcount
            == 1
        )


def test_any_role_can_append_to_the_audit_log_but_only_an_admin_can_read_it(
    engine: Engine,
) -> None:
    for subject, role in (
        ("m1", "mentor"),
        ("f1", "faculty"),
        ("boss", "staff"),
        ("root", "admin"),
    ):
        with as_user(engine, subject, role) as conn:
            append(
                conn,
                actor_kind=role,
                actor_id=subject,
                action="test.ping",
                subject_kind="test",
                subject_ref=None,
            )
    with as_user(engine, "m1", "mentor") as conn:
        assert conn.execute(text("SELECT count(*) FROM gov.audit_log")).scalar_one() == 0
    with as_user(engine, "root", "admin") as conn:
        assert conn.execute(text("SELECT count(*) FROM gov.audit_log")).scalar_one() == 4
        assert verify(conn).ok and verify(conn).checked == 4


@pytest.mark.parametrize(
    "sql", ["UPDATE gov.audit_log SET action = 'x'", "DELETE FROM gov.audit_log"]
)
def test_not_even_an_admin_can_change_or_delete_audit_rows(engine: Engine, sql: str) -> None:
    with as_user(engine, "root", "admin") as conn:
        append(
            conn,
            actor_kind="admin",
            actor_id="root",
            action="test.ping",
            subject_kind="test",
            subject_ref=None,
        )
    with (
        pytest.raises(DBAPIError, match="permission denied"),
        as_user(engine, "root", "admin") as conn,
    ):
        conn.execute(text(sql))


def test_the_case_engine_works_through_the_api_role_for_the_owner_and_hides_other_cases(
    engine: Engine,
) -> None:
    with as_user(engine, "m1", "mentor") as conn:
        advance(conn, 1, Action.DISMISS, Actor.MENTOR, "m1", DAY)
    with as_user(engine, "m1", "mentor") as conn, pytest.raises(LookupError):
        advance(conn, 2, Action.DISMISS, Actor.MENTOR, "m1", DAY)  # m2's case: invisible
    with as_user(engine, "boss", "staff") as conn:
        advance(conn, 2, Action.DISMISS, Actor.STAFF, "boss", DAY)
    with engine.connect() as owner:
        states = owner.execute(text("SELECT id, state FROM app.cases ORDER BY id")).all()
        assert [tuple(r) for r in states] == [(1, "dismissed"), (2, "dismissed")]
        assert verify(owner).ok
        actions = owner.execute(text("SELECT action FROM gov.audit_log ORDER BY seq")).scalars()
        assert list(actions) == ["case.dismiss", "case.dismiss"]


def test_identity_does_not_leak_into_the_next_use_of_a_pooled_connection(engine: Engine) -> None:
    with as_user(engine, "m1", "mentor") as conn:
        assert ids(conn, CASES) == [1]
    with engine.begin() as conn:  # pool_size=1, so this is the same connection
        assert conn.execute(text("SELECT current_user")).scalar_one() != "app_api_role"
        assert conn.execute(text("SELECT current_setting('app.role', true)")).scalar() in (None, "")
        assert ids(conn, CASES) == [1, 2]  # the owner is not subject to the policies


def test_a_subject_that_looks_like_sql_is_only_a_name(engine: Engine) -> None:
    with as_user(engine, "m1'; DROP TABLE app.cases;--", "mentor") as conn:
        assert ids(conn, CASES) == []
    with engine.connect() as owner:
        assert owner.execute(text("SELECT count(*) FROM app.cases")).scalar_one() == 2


def test_migration_0007_downgrades_and_upgrades_again(engine: Engine) -> None:
    engine.dispose()
    _alembic("downgrade", "0006")
    _alembic("upgrade", "head")
    eng = create_engine(TEST_DB or "")
    try:
        with eng.connect() as conn:
            on = conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE oid = 'app.cases'::regclass")
            ).scalar_one()
            assert on is True
    finally:
        eng.dispose()
