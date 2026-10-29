"""Department overview for staff and admin: how many cases are open and where they sit.

Counts only. No student id, name, score or probability appears here, and the bands are the same
two labels the case screens use. The mentor ids are the ones the caseload already shows to
these roles. Row-level security still applies (staff and admin see every case).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection, text

from app.api.deps import get_conn, require_roles
from app.cases.states import OPEN_STATES
from app.core.auth import Principal, Role

OVERVIEW_READERS = (Role.STAFF, Role.ADMIN)
OPEN_VALUES = sorted(s.value for s in OPEN_STATES)
BANDS = ("amber", "red")

router = APIRouter(prefix="/api", tags=["overview"])

Conn = Annotated[Connection, Depends(get_conn, scope="function")]
Reader = Annotated[Principal, Depends(require_roles(*OVERVIEW_READERS))]


class MentorLoad(BaseModel):
    mentor_id: str
    open: int
    overdue: int


class Overview(BaseModel):
    open_cases: int
    overdue: int
    by_state: dict[str, int]
    by_band: dict[str, int]
    by_mentor: list[MentorLoad]
    unassigned_students: int


@router.get("/overview")
def department_overview(_: Reader, conn: Conn) -> Overview:
    rows = conn.execute(
        text(
            "SELECT state, band, mentor_id, count(*) AS n, "
            "count(*) FILTER (WHERE overdue_noted) AS late "
            "FROM app.cases WHERE state = ANY(:open) GROUP BY state, band, mentor_id"
        ),
        {"open": OPEN_VALUES},
    ).all()
    by_state = dict.fromkeys(OPEN_VALUES, 0)
    by_band = dict.fromkeys(BANDS, 0)
    mentors: dict[str, list[int]] = {}
    for row in rows:
        by_state[row.state] += int(row.n)
        by_band[row.band] += int(row.n)
        load = mentors.setdefault(row.mentor_id, [0, 0])
        load[0] += int(row.n)
        load[1] += int(row.late)
    unassigned = conn.execute(text("SELECT app.unassigned_student_count()")).scalar()
    return Overview(
        open_cases=sum(by_state.values()),
        overdue=sum(load[1] for load in mentors.values()),
        by_state=by_state,
        by_band=by_band,
        by_mentor=[
            MentorLoad(mentor_id=m, open=n, overdue=late)
            for m, (n, late) in sorted(mentors.items(), key=lambda kv: (-kv[1][0], kv[0]))
        ],
        unassigned_students=int(unassigned or 0),
    )
