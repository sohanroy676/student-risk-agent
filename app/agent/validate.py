"""The gate between the model and `save_plan`. Pure.

Whatever the model returns either becomes a `Plan` that passed every rule here or is refused
with `InvalidPlan`, and the caller falls back to the template. Error texts never repeat model
output beyond a banned word, so a hostile reply cannot reach logs or events through them.
Mentor edits go through `check_message` only; the extra rules here are for agent text.
"""

import json
import re
from typing import Any

from pydantic import ValidationError

from app.agent.crisis import is_crisis, normalise
from app.agent.schema import Claim, InvalidPlan, Plan
from app.cases.drafts import BANNED, CONTROL, InvalidMessage, check_message

MAX_RAW_CHARS = 20_000

URL = re.compile(
    r"https?:|ftp:|www\.|\b[\w-]+\.(?:com|in|org|edu|net|io|co|ac|gov|app|me|ly|xyz)\b",
    re.IGNORECASE,
)
EMAIL = re.compile(r"\S+\s*(?:@|\[at\]|\(at\))\s*\S+", re.IGNORECASE)
PHONE = re.compile(r"\d(?:[\s().+-]*\d){6,}")  # seven or more digits, however spaced
INTERNAL_REF = re.compile(r"\bcase[-\s_]?\d+|\bfact[-\s_]?id|\bstudent[-\s_]?id", re.IGNORECASE)


def _clean(text: str, where: str, *, student_facing: bool) -> str:
    """The normalised text, or `InvalidPlan` naming only the field and the broken rule."""
    clean = normalise(text).strip()
    if not clean:
        raise InvalidPlan(f"{where} is empty")
    if CONTROL.search(clean):
        raise InvalidPlan(f"{where} contains control characters")
    found = BANNED.search(clean)
    if found:
        raise InvalidPlan(f"{where} contains the banned word '{found.group(0).lower()}'")
    for pattern, label in (
        (URL, "a link"),
        (EMAIL, "an email address"),
        (INTERNAL_REF, "an internal reference"),
    ):
        if pattern.search(clean):
            raise InvalidPlan(f"{where} contains {label}")
    if student_facing and PHONE.search(clean):  # claims may hold dates, which look like phones
        raise InvalidPlan(f"{where} contains a phone number")
    if student_facing and is_crisis([clean]):
        raise InvalidPlan(f"{where} contains crisis wording")
    return clean


def check_plan(plan: Plan, known_fact_ids: set[str]) -> Plan:
    """The plan with normalised text and de-duplicated citations, or `InvalidPlan`.

    The message must also pass `check_message`; every citation must be a known fact id, and the
    case must have at least one fact to cite.
    """
    if not known_fact_ids:
        raise InvalidPlan("the case has no facts to cite")
    message = _clean(plan.message, "the message", student_facing=True)
    try:
        message = check_message(message)
    except InvalidMessage as exc:
        raise InvalidPlan(f"the message: {exc}") from exc
    claims: list[Claim] = []
    for n, claim in enumerate(plan.rationale, 1):
        ids = list(dict.fromkeys(claim.fact_ids))
        if not set(ids) <= known_fact_ids:
            raise InvalidPlan(f"claim {n} cites a fact the case does not have")
        claims.append(
            Claim(text=_clean(claim.text, f"claim {n}", student_facing=False), fact_ids=ids)
        )
    steps = [_clean(s, f"step {n}", student_facing=False) for n, s in enumerate(plan.steps, 1)]
    return Plan(message=message, rationale=claims, steps=steps)


def validate_plan(raw: Any, known_fact_ids: set[str]) -> Plan:
    """Parse and check a model reply (JSON text or an already-decoded object).

    Raises only `InvalidPlan`, whatever `raw` is.
    """
    data = raw
    if isinstance(raw, bytes | str):
        if len(raw) > MAX_RAW_CHARS:
            raise InvalidPlan("the reply is too long")
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise InvalidPlan("the reply is not valid JSON") from exc
    if not isinstance(data, dict):
        raise InvalidPlan("the reply is not a JSON object")
    try:
        plan = Plan.model_validate(data)
    except (ValidationError, RecursionError) as exc:
        raise InvalidPlan("the reply does not match the plan format") from exc
    return check_plan(plan, known_fact_ids)
