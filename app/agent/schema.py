"""What the drafting agent reads and writes. Pure.

Nothing here can carry a probability, score, band, student id or name: the agent knows a case
only by its reference (`case-<id>`) and the facts the tools give it. Every claim in a plan cites
the `fact_id`s it rests on; `save_plan` refuses ids the case does not have.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_CLAIMS = 5
MAX_STEPS = 5

Step = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class InvalidPlan(ValueError):
    """The plan cannot be saved; the text says why."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(_Strict):
    """One statement for the mentor, with the facts it rests on."""

    text: str = Field(min_length=1, max_length=300)
    fact_ids: list[str] = Field(min_length=1, max_length=5)


class Plan(_Strict):
    """A draft: the message for the student, why, and what the mentor might do."""

    message: str = Field(min_length=1, max_length=1000)
    rationale: list[Claim] = Field(min_length=1, max_length=MAX_CLAIMS)
    steps: list[Step] = Field(min_length=1, max_length=MAX_STEPS)


class CaseFacts(_Strict):
    case_ref: str
    cycle: int
    state: str
    days_open: int


class Fact(_Strict):
    fact_id: str
    kind: str  # "reason" or "concern"
    text: str


class FactList(_Strict):
    facts: list[Fact]
