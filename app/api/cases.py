"""Case endpoints for mentors and staff: caseload, case detail, and the actions on a case.

Who sees what is decided twice: here by role, and in the database by row-level security (a
mentor's connection can only read their own mentees' cases). A case the caller may not see is
indistinguishable from one that does not exist (404). The responses carry the band but never
the probability or any score; reasons go to mentors and staff only, and the actor on an action
always comes from the token, never from the request.
"""

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from app.api.deps import (
    Denial,
    denied,
    get_conn,
    get_denial_recorder,
    get_today,
    require_roles,
)
from app.cases.drafts import InvalidMessage
from app.cases.states import OPEN_STATES, Action, Actor, State, WrongActor, WrongState
from app.cases.store import advance, edit_draft
from app.core.auth import Principal, Role

CASE_READERS = (Role.MENTOR, Role.STAFF, Role.ADMIN)
REASON_READERS = (Role.MENTOR, Role.STAFF)  # the draft message has the same audience
CASE_ACTORS = {Role.MENTOR: Actor.MENTOR, Role.STAFF: Actor.STAFF}
OPEN_VALUES = sorted(s.value for s in OPEN_STATES)
# The only event details a client may see (the stored detail is free-form JSON).
VISIBLE_DETAIL_KEYS = ("reason", "auto_escalated")
NOT_FOUND = HTTPException(status_code=404, detail="case not found")

router = APIRouter(prefix="/api", tags=["cases"])

Conn = Annotated[Connection, Depends(get_conn, scope="function")]


class CaseSummary(BaseModel):
    id: int
    student_id: int
    mentor_id: str
    state: State
    band: Literal["amber", "red"]
    reason: Literal["red", "rapid_rise"]
    cycle: int
    opened_on: date
    entered_on: date
    due_on: date | None
    overdue: bool
    approved_by: str | None
    approved_on: date | None


class CasePage(BaseModel):
    items: list[CaseSummary]
    total: int
    limit: int
    offset: int


class TimelineEvent(BaseModel):
    on_date: date
    kind: str
    from_state: str | None
    to_state: str | None
    actor_kind: str
    actor_id: str | None
    detail: dict[str, str | bool]


class CaseReason(BaseModel):
    rank: int
    fact_id: str
    feature: str
    text: str


class Draft(BaseModel):
    version: int
    source: Literal["template", "agent", "mentor"]
    author: str
    created_on: date
    message: str


class CaseDetail(CaseSummary):
    timeline: list[TimelineEvent]
    reasons: list[CaseReason]
    draft: Draft | None


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "dismiss", "continue", "resolve", "escalate"]


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(max_length=5000)  # the real limit is in check_message


class DraftResult(BaseModel):
    id: int
    version: int


class ActionResult(BaseModel):
    id: int
    state: State


CASE_COLUMNS = (
    "id, student_id, mentor_id, state, band, reason, cycle, opened_on, entered_on, due_on, "
    "overdue_noted AS overdue, approved_by, approved_on"
)


@router.get("/caseload")
def caseload(
    principal: Annotated[Principal, Depends(require_roles(*CASE_READERS))],
    conn: Conn,
    state: State | None = None,
    mentor: Annotated[str | None, Query(max_length=255)] = None,
    include_closed: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> CasePage:
    """Cases the caller may see, most urgent first (open cases only unless asked)."""
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if state is not None:
        where.append("state = :state")
        params["state"] = state.value
    elif not include_closed:
        where.append("state = ANY(:open)")
        params["open"] = OPEN_VALUES
    if mentor is not None:
        where.append("mentor_id = :mentor")
        params["mentor"] = mentor
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(text(f"SELECT count(*) FROM app.cases {clause}"), params).scalar_one()  # noqa: S608
    rows = conn.execute(
        text(
            f"SELECT {CASE_COLUMNS} FROM app.cases {clause} "  # noqa: S608
            "ORDER BY due_on NULLS LAST, id LIMIT :limit OFFSET :offset"
        ),
        params,
    ).mappings()
    return CasePage(
        items=[CaseSummary(**row) for row in rows], total=int(total), limit=limit, offset=offset
    )


def _clean_detail(raw: dict[str, Any] | None) -> dict[str, str | bool]:
    return {
        key: value
        for key, value in (raw or {}).items()
        if key in VISIBLE_DETAIL_KEYS and isinstance(value, str | bool)
    }


@router.get("/cases/{case_id}")
def case_detail(
    case_id: int,
    principal: Annotated[Principal, Depends(require_roles(*CASE_READERS))],
    conn: Conn,
) -> CaseDetail:
    row = (
        conn.execute(
            text(f"SELECT {CASE_COLUMNS} FROM app.cases WHERE id = :id"),  # noqa: S608
            {"id": case_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise NOT_FOUND
    events = conn.execute(
        text(
            "SELECT on_date, kind, from_state, to_state, actor_kind, actor_id, detail "
            "FROM app.case_events WHERE case_id = :id ORDER BY id"
        ),
        {"id": case_id},
    ).mappings()
    reasons: list[CaseReason] = []
    draft: Draft | None = None
    if principal.role in REASON_READERS:
        found = conn.execute(
            text(
                "SELECT rank, fact_id, feature, text FROM app.case_reasons WHERE case_id = :id "
                "AND as_of = (SELECT max(as_of) FROM app.case_reasons WHERE case_id = :id) "
                "ORDER BY rank"
            ),
            {"id": case_id},
        ).mappings()
        reasons = [CaseReason(**r) for r in found]
        latest = (
            conn.execute(
                text(
                    "SELECT version, source, author, created_on, message FROM app.case_drafts "
                    "WHERE case_id = :id ORDER BY version DESC LIMIT 1"
                ),
                {"id": case_id},
            )
            .mappings()
            .one_or_none()
        )
        draft = None if latest is None else Draft(**latest)
    return CaseDetail(
        **row,
        timeline=[TimelineEvent(**{**e, "detail": _clean_detail(e["detail"])}) for e in events],
        reasons=reasons,
        draft=draft,
    )


@router.post("/cases/{case_id}/actions")
def act_on_case(
    case_id: int,
    body: ActionRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_roles(Role.MENTOR, Role.STAFF))],
    conn: Conn,
    today: Annotated[date, Depends(get_today)],
    recorder: Annotated[Denial, Depends(get_denial_recorder)],
) -> ActionResult:
    """Approve, dismiss, continue, resolve or escalate. The rules live in the state machine."""
    try:
        new_state = advance(
            conn,
            case_id,
            Action(body.action),
            CASE_ACTORS[principal.role],
            principal.subject,
            today,
        )
    except LookupError:
        raise NOT_FOUND from None
    except WrongActor as error:
        raise denied(recorder, request, principal.subject, principal.role.value) from error
    except WrongState as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ActionResult(id=case_id, state=new_state)


@router.put("/cases/{case_id}/draft")
def put_draft(
    case_id: int,
    body: DraftRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_roles(Role.MENTOR))],
    conn: Conn,
    today: Annotated[date, Depends(get_today)],
    recorder: Annotated[Denial, Depends(get_denial_recorder)],
) -> DraftResult:
    """The case's own mentor rewords the draft while it waits for approval (never after)."""
    try:
        version = edit_draft(conn, case_id, body.message, principal.subject, today)
    except LookupError:
        raise NOT_FOUND from None
    except WrongActor as error:
        raise denied(recorder, request, principal.subject, principal.role.value) from error
    except WrongState as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except InvalidMessage as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return DraftResult(id=case_id, version=version)
