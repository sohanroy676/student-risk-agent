"""The agent's read-only tools, bound to one case.

The case is fixed when the toolbox is made, so nothing the model sends can reach another case.
Tools take no arguments, return the case reference and plain facts (never names, roll numbers,
contact details, protected attributes, probabilities or bands) and cannot change anything. A
concern appears as its category and date only: the free-text note never reaches the model.
"""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Connection, text

from app.agent.schema import CaseFacts, Fact, FactList

CONCERN_WINDOW_DAYS = 30
MAX_CONCERNS = 5
READ_TOOLS = ("get_case", "get_reasons", "get_concerns")


class UnknownTool(LookupError):
    """The model asked for a tool that does not exist."""


class BadToolArguments(ValueError):
    """The model passed arguments to a tool that takes none."""


class CaseTools:
    def __init__(self, conn: Connection, case_id: int, today: date) -> None:
        self._conn = conn
        self._case_id = case_id
        self._today = today

    @property
    def case_ref(self) -> str:
        return f"case-{self._case_id}"

    def get_case(self) -> CaseFacts:
        row = self._conn.execute(
            text("SELECT state, cycle, opened_on FROM app.cases WHERE id = :id"),
            {"id": self._case_id},
        ).one_or_none()
        if row is None:
            raise LookupError(f"no case {self._case_id}")
        return CaseFacts(
            case_ref=self.case_ref,
            cycle=row.cycle,
            state=row.state,
            days_open=max((self._today - row.opened_on).days, 0),
        )

    def get_reasons(self) -> FactList:
        """The reasons from the latest night, as stored (mentor-facing value sentences)."""
        found = self._conn.execute(
            text(
                "SELECT fact_id, text FROM app.case_reasons WHERE case_id = :id "
                "AND as_of = (SELECT max(as_of) FROM app.case_reasons WHERE case_id = :id) "
                "ORDER BY rank"
            ),
            {"id": self._case_id},
        ).tuples()
        return FactList(facts=[Fact(fact_id=f, kind="reason", text=t) for f, t in found])

    def get_concerns(self) -> FactList:
        """Concerns faculty raised about this case's student in the last 30 days: category
        and date only."""
        found = self._conn.execute(
            text(
                "SELECT n.id, n.category, n.raised_on FROM app.concerns n "
                "WHERE n.student_id = (SELECT student_id FROM app.cases WHERE id = :id) "
                "AND n.raised_on <= :today AND n.raised_on > :since "
                "ORDER BY n.raised_on DESC, n.id DESC LIMIT :limit"
            ),
            {
                "id": self._case_id,
                "today": self._today,
                "since": self._today - timedelta(days=CONCERN_WINDOW_DAYS),
                "limit": MAX_CONCERNS,
            },
        ).tuples()
        return FactList(
            facts=[
                Fact(
                    fact_id=f"{self.case_ref}/concern-{cid}/{raised.isoformat()}",
                    kind="concern",
                    text=f"A faculty member raised a {category} concern on {raised.isoformat()}.",
                )
                for cid, category, raised in found
            ]
        )

    def known_fact_ids(self) -> set[str]:
        """Every fact id a plan for this case may cite."""
        return {f.fact_id for f in self.get_reasons().facts + self.get_concerns().facts}


def tool_specs() -> list[dict[str, Any]]:
    """Provider-neutral tool definitions: name, description, input schema (no inputs)."""
    empty: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
    return [
        {
            "name": "get_case",
            "description": "The case reference, cycle (1 = first outreach), state and days open.",
            "input_schema": empty,
        },
        {
            "name": "get_reasons",
            "description": "Up to three plain reasons for the case, each with a fact_id to cite.",
            "input_schema": empty,
        },
        {
            "name": "get_concerns",
            "description": (
                "Concerns faculty raised in the last 30 days (category and date), each with "
                "a fact_id to cite."
            ),
            "input_schema": empty,
        },
    ]


def run_tool(tools: CaseTools, name: str, args: dict[str, Any] | None = None) -> BaseModel:
    """Run one read tool by name. Unknown names and any arguments are refused."""
    if name not in READ_TOOLS:
        raise UnknownTool(name)
    if args:
        raise BadToolArguments(f"{name} takes no arguments")
    handler: Callable[[], BaseModel] = getattr(tools, name)
    return handler()
