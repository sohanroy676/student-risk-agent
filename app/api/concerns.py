"""Concerns: faculty tell a student's mentor about something they noticed.

A concern is a note for people. It opens no case, touches no band and decides nothing, and
these endpoints never return a band, score or case. Faculty can add concerns and read only their
own; a mentor reads concerns about their own mentees and acknowledges them; staff read and
acknowledge all; admin has no access. Row-level security enforces the same rules in the
database. The note is free text: it is length-limited and kept out of the audit log (which
carries only the concern reference and its category).
"""

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_conn, get_today, require_roles
from app.core import audit_store
from app.core.auth import Principal, Role

DAILY_LIMIT = 20  # concerns one faculty member may raise per day
MAX_NOTE = 500
MAX_ID = 2**31 - 1
READERS = (Role.FACULTY, Role.MENTOR, Role.STAFF)
ACKNOWLEDGERS = (Role.MENTOR, Role.STAFF)
OVERSEERS = (Role.MENTOR, Role.STAFF)  # may see who raised a concern and who acknowledged it

router = APIRouter(prefix="/api/concerns", tags=["concerns"])

Conn = Annotated[Connection, Depends(get_conn, scope="function")]
Category = Literal["attendance", "performance", "wellbeing", "behaviour", "other"]
Note = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, max_length=MAX_NOTE, pattern=r"^[^\x00-\x09\x0b-\x1f\x7f]*$"
    ),
]


class ConcernRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: Annotated[int, Field(ge=1, le=MAX_ID)]
    category: Category
    note: Note = ""


class ConcernCreated(BaseModel):
    id: int


class ConcernOut(BaseModel):
    id: int
    student_id: int
    category: Category
    raised_on: date
    note: str
    acknowledged: bool
    raised_by: str | None  # mentor and staff only
    acknowledged_by: str | None  # mentor and staff only
    acknowledged_on: date | None


class ConcernPage(BaseModel):
    items: list[ConcernOut]
    total: int
    limit: int
    offset: int


COLUMNS = "id, student_id, category, raised_on, note, raised_by, acknowledged_by, acknowledged_on"


def _out(row: Any, principal: Principal) -> ConcernOut:
    overseer = principal.role in OVERSEERS
    return ConcernOut(
        id=row.id,
        student_id=row.student_id,
        category=row.category,
        raised_on=row.raised_on,
        note=row.note,
        acknowledged=row.acknowledged_by is not None,
        raised_by=row.raised_by if overseer else None,
        acknowledged_by=row.acknowledged_by if overseer else None,
        acknowledged_on=row.acknowledged_on if overseer else None,
    )


@router.post("")
def raise_concern(
    body: ConcernRequest,
    principal: Annotated[Principal, Depends(require_roles(Role.FACULTY))],
    conn: Conn,
    today: Annotated[date, Depends(get_today)],
) -> ConcernCreated:
    """Add a concern about a student. At most `DAILY_LIMIT` a day per faculty member."""
    raised_today = conn.execute(
        text("SELECT count(*) FROM app.concerns WHERE raised_by = :u AND raised_on = :d"),
        {"u": principal.subject, "d": today},
    ).scalar_one()
    if raised_today >= DAILY_LIMIT:
        raise HTTPException(status_code=429, detail="daily limit of concerns reached")
    try:
        with conn.begin_nested():
            concern_id = conn.execute(
                text(
                    "INSERT INTO app.concerns (student_id, raised_by, raised_on, category, note) "
                    "VALUES (:s, :u, :d, :c, :n) RETURNING id"
                ),
                {
                    "s": body.student_id,
                    "u": principal.subject,
                    "d": today,
                    "c": body.category,
                    "n": body.note,
                },
            ).scalar_one()
    except IntegrityError:  # no such student; the savepoint keeps the transaction usable
        raise HTTPException(status_code=404, detail="student not found") from None
    audit_store.append(
        conn,
        actor_kind=principal.role.value,
        actor_id=principal.subject,
        action="concern.raised",
        subject_kind="concern",
        subject_ref=f"concern-{concern_id}",
        detail={"category": body.category},
    )
    return ConcernCreated(id=int(concern_id))


@router.get("")
def list_concerns(
    principal: Annotated[Principal, Depends(require_roles(*READERS))],
    conn: Conn,
    student_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
    open_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ConcernPage:
    """The concerns the caller may see, newest first (row security does the narrowing)."""
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if student_id is not None:
        where.append("student_id = :student")
        params["student"] = student_id
    if open_only:
        where.append("acknowledged_by IS NULL")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(text(f"SELECT count(*) FROM app.concerns {clause}"), params).scalar_one()  # noqa: S608
    rows = conn.execute(
        text(
            f"SELECT {COLUMNS} FROM app.concerns {clause} "  # noqa: S608
            "ORDER BY raised_on DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return ConcernPage(
        items=[_out(row, principal) for row in rows], total=int(total), limit=limit, offset=offset
    )


@router.post("/{concern_id}/acknowledge")
def acknowledge_concern(
    concern_id: Annotated[int, Path(ge=1, le=2**63 - 1)],
    principal: Annotated[Principal, Depends(require_roles(*ACKNOWLEDGERS))],
    conn: Conn,
    today: Annotated[date, Depends(get_today)],
) -> ConcernOut:
    """Mark a concern as seen. A concern the caller may not see is the same 404 as a missing one."""
    row = conn.execute(
        text(f"SELECT {COLUMNS} FROM app.concerns WHERE id = :id FOR UPDATE"),  # noqa: S608
        {"id": concern_id},
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="concern not found")
    if row.acknowledged_by is not None:
        raise HTTPException(status_code=409, detail="concern already acknowledged")
    conn.execute(
        text("UPDATE app.concerns SET acknowledged_by = :u, acknowledged_on = :d WHERE id = :id"),
        {"u": principal.subject, "d": today, "id": concern_id},
    )
    audit_store.append(
        conn,
        actor_kind=principal.role.value,
        actor_id=principal.subject,
        action="concern.acknowledged",
        subject_kind="concern",
        subject_ref=f"concern-{concern_id}",
        detail={"category": row.category},
    )
    done = conn.execute(
        text(f"SELECT {COLUMNS} FROM app.concerns WHERE id = :id"),  # noqa: S608
        {"id": concern_id},
    ).one()
    return _out(done, principal)
