import contextlib
import json
import re
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.agent.schema import CaseFacts, Claim, Fact, FactList, Plan
from app.agent.tools import BadToolArguments, UnknownTool, run_tool, tool_specs

# Field names that could carry a risk figure or identify a student.
FORBIDDEN = re.compile(
    r"prob|score|band|risk|student_id|name|roll|phone|email|mobile|gender|region|disab",
    re.IGNORECASE,
)
MODELS = (Plan, Claim, CaseFacts, Fact, FactList)


def _property_names(schema: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        names.update(schema.get("properties", {}))
        for value in schema.values():
            names |= _property_names(value)
    elif isinstance(schema, list):
        for value in schema:
            names |= _property_names(value)
    return names


def _plan(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "message": "Hi, checking in.",
        "rationale": [{"text": "Quiet on the LMS.", "fact_ids": ["case-1/x/2026-03-02"]}],
        "steps": ["Offer a meeting this week."],
    }
    return {**base, **over}


@pytest.mark.parametrize("model", MODELS)
def test_no_model_has_a_field_that_could_carry_a_score_or_identity(model: Any) -> None:
    names = _property_names(model.model_json_schema())
    assert names
    assert not [n for n in names if FORBIDDEN.search(n)]


def test_a_valid_plan_parses() -> None:
    assert Plan.model_validate(_plan()).steps == ["Offer a meeting this week."]


@pytest.mark.parametrize(
    "bad",
    [
        _plan(message=""),
        _plan(message="x" * 1001),
        _plan(rationale=[]),
        _plan(rationale=[{"text": "a", "fact_ids": []}]),
        _plan(rationale=[{"text": "", "fact_ids": ["f"]}]),
        _plan(rationale=[{"text": "a" * 301, "fact_ids": ["f"]}]),
        _plan(rationale=[{"text": "a", "fact_ids": ["f"]}] * 6),
        _plan(steps=[]),
        _plan(steps=[""]),
        _plan(steps=["s" * 201]),
        _plan(steps=["s"] * 6),
        _plan(extra="no"),
        _plan(probability=0.9),
        _plan(rationale=[{"text": "a", "fact_ids": ["f"], "score": 1}]),
    ],
)
def test_bad_plans_are_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Plan.model_validate(bad)


@given(st.text(max_size=400), st.text(max_size=400))
def test_any_text_either_parses_or_raises_validation_error(message: str, step: str) -> None:
    with contextlib.suppress(ValidationError):
        Plan.model_validate(_plan(message=message, steps=[step]))


def test_tool_specs_name_each_read_tool_and_take_no_inputs() -> None:
    specs = tool_specs()
    assert [s["name"] for s in specs] == ["get_case", "get_reasons", "get_concerns"]
    for spec in specs:
        assert spec["input_schema"]["properties"] == {}
        assert spec["input_schema"]["additionalProperties"] is False
        json.dumps(spec)  # a provider can serialise it


def test_there_is_no_tool_that_writes_or_sends() -> None:
    names = {s["name"] for s in tool_specs()}
    assert not [n for n in names if re.search(r"save|send|update|delete|set|write", n)]


def test_run_tool_refuses_unknown_names_and_any_arguments() -> None:
    with pytest.raises(UnknownTool):
        run_tool(None, "send_message")  # type: ignore[arg-type]
    with pytest.raises(UnknownTool):
        run_tool(None, "save_plan", {"message": "x"})  # type: ignore[arg-type]
    with pytest.raises(BadToolArguments):
        run_tool(None, "get_case", {"case_id": 2})  # type: ignore[arg-type]
