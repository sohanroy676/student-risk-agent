"""Admin endpoints: who mentors whom, the last nightly run, and the audit log and its check.

Admin only. The actor on every write comes from the token. Nothing here returns a score or
band, and the audit entries written carry counts and references, never mentor-student pairs.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import Connection, text

from app.api.deps import get_conn, get_today, require_roles
from app.cases.store import UnknownStudent, assign_mentor
from app.core import audit_store
from app.core.audit import Anchor
from app.core.auth import Principal, Role

# What the "latest run" answer may show from the stored detail (counts and flags only).
RUN_DETAIL_KEYS = (
    "as_of",
    "data_quality",
    "skipped",
    "model_week",
    "students_evaluated",
    "cases_opened",
    "deferred",
    "unassigned",
    "reasons_written",
    "drafted",
    "moved_to_review",
    "newly_overdue",
    "cause",
)
MAX_STUDENT_ID = 2**31 - 1
HASH_PREFIX_LENGTH = 12
# No `detail` column on purpose. A missing `action` filter (NULL) matches every row.
COUNT_AUDIT = (
    "SELECT count(*) FROM gov.audit_log "
    "WHERE (CAST(:action AS text) IS NULL OR action = CAST(:action AS text))"
)
LIST_AUDIT = (
    "SELECT seq, at, actor_kind, actor_id, action, subject_kind, subject_ref, "
    "left(hash, :prefix) AS hash_prefix FROM gov.audit_log "
    "WHERE (CAST(:action AS text) IS NULL OR action = CAST(:action AS text)) "
    "ORDER BY seq DESC LIMIT :limit OFFSET :offset"
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

Conn = Annotated[Connection, Depends(get_conn, scope="function")]
Admin = Annotated[Principal, Depends(require_roles(Role.ADMIN))]
MentorId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mentor_id: MentorId


class AssignmentResult(BaseModel):
    student_id: int
    changed: bool
    cases_moved: int


class NightlyRun(BaseModel):
    seq: int
    at: str
    action: str
    detail: dict[str, Any]


class AuditEntry(BaseModel):
    """One audit row without its `detail`: who did what to which record, and when."""

    seq: int
    at: str
    actor_kind: str
    actor_id: str | None
    action: str
    subject_kind: str
    subject_ref: str | None
    hash_prefix: str


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
    limit: int
    offset: int


class AuditCheck(BaseModel):
    ok: bool
    checked: int
    first_bad_seq: int | None
    problem: str | None
    anchor: str | None


@router.put("/mentor-assignments/{student_id}")
def put_mentor_assignment(
    student_id: Annotated[int, Path(ge=1, le=MAX_STUDENT_ID)],
    body: AssignmentRequest,
    principal: Admin,
    conn: Conn,
    today: Annotated[date, Depends(get_today)],
) -> AssignmentResult:
    """Assign or reassign a mentor; the student's open case moves with it."""
    try:
        result = assign_mentor(conn, student_id, body.mentor_id, principal.subject, today)
    except UnknownStudent:
        raise HTTPException(status_code=404, detail="student not found") from None
    return AssignmentResult(
        student_id=student_id, changed=result.changed, cases_moved=result.cases_moved
    )


@router.get("/nightly/latest")
def latest_nightly_run(_: Admin, conn: Conn) -> NightlyRun:
    row = conn.execute(
        text(
            "SELECT seq, at, action, detail FROM gov.audit_log "
            "WHERE action IN ('nightly.run', 'nightly.halted') ORDER BY seq DESC LIMIT 1"
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no nightly run recorded")
    detail = {k: v for k, v in dict(row.detail).items() if k in RUN_DETAIL_KEYS}
    return NightlyRun(seq=int(row.seq), at=row.at.isoformat(), action=row.action, detail=detail)


@router.get("/audit")
def list_audit_entries(
    _: Admin,
    conn: Conn,
    action: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> AuditPage:
    """Newest first. The stored `detail` is never returned, only the fields named above."""
    total = conn.execute(text(COUNT_AUDIT), {"action": action}).scalar()
    rows = conn.execute(
        text(LIST_AUDIT),
        {"action": action, "prefix": HASH_PREFIX_LENGTH, "limit": limit, "offset": offset},
    ).all()
    return AuditPage(
        items=[
            AuditEntry(
                seq=int(r.seq),
                at=r.at.isoformat(),
                actor_kind=r.actor_kind,
                actor_id=r.actor_id,
                action=r.action,
                subject_kind=r.subject_kind,
                subject_ref=r.subject_ref,
                hash_prefix=r.hash_prefix,
            )
            for r in rows
        ],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get("/audit/verify")
def verify_audit_log(
    _: Admin, conn: Conn, anchor: Annotated[str | None, Query(max_length=100)] = None
) -> AuditCheck:
    """Recompute the hash chain; with an `anchor` kept elsewhere, also detect cut-off rows."""
    try:
        expected = None if anchor is None else Anchor.parse(anchor)
    except ValueError:
        raise HTTPException(status_code=422, detail="anchor must look like SEQ:HASH") from None
    result = audit_store.verify(conn, expected)
    head = audit_store.current_anchor(conn)
    return AuditCheck(
        ok=result.ok,
        checked=result.checked,
        first_bad_seq=result.first_bad_seq,
        problem=result.problem,
        anchor=None if head is None else str(head),
    )
