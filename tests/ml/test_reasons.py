import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.features.snapshot import FEATURE_NAMES
from app.ml.reasons import TEMPLATES, render

PERCENT = {
    "attendance_rate",
    "attendance_rate_28d",
    "marks_pct_mean",
    "marks_pct_last",
    "marks_pct_min",
}
SIGNED = {"lms_trend", "submit_lead_days_mean"}
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def shown_number(text: str) -> float | None:
    found = NUMBER.findall(text)
    assert len(found) <= 1, f"more than one number in {text!r}"
    return float(found[0].replace(",", "")) if found else None


def check_matches(feature: str, value: float) -> None:
    """The one number in the text is `value` in the unit the sentence uses, within rounding."""
    text = render(feature, value)
    number = shown_number(text)
    if feature in PERCENT:
        expected, tolerance = value * 100, 0.5
    elif feature == "submit_lead_days_mean":
        expected, tolerance = abs(value), 0.05
    else:
        expected, tolerance = abs(value), 0.5
    if number is None:  # only the "unchanged" / "on the deadline" wordings drop the number
        assert feature in SIGNED, text
        assert abs(value) < tolerance + 1e-9, text
    else:
        assert abs(number - expected) <= tolerance + 1e-9, f"{text!r} for {value}"
    if feature in SIGNED and number is not None:
        up, down = ("rose", "fell") if feature == "lms_trend" else ("before", "after")
        assert (up if value > 0 else down) in text, text


def test_every_feature_has_a_template_and_nothing_else() -> None:
    assert set(TEMPLATES) == set(FEATURE_NAMES)


@pytest.mark.parametrize("feature", FEATURE_NAMES)
@pytest.mark.parametrize("value", [0.0, 1.0, 0.5, 0.625, 3.0, 12.34, 1234.5, -2.5, -0.04, 0.04])
def test_rendered_value_matches_for_awkward_numbers(feature: str, value: float) -> None:
    if value < 0 and feature not in SIGNED:
        pytest.skip("only signed features can be negative")
    check_matches(feature, value)


@given(
    feature=st.sampled_from(FEATURE_NAMES),
    value=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False),
)
def test_rendered_value_matches_for_any_finite_value(feature: str, value: float) -> None:
    if value < 0 and feature not in SIGNED:
        value = abs(value)
    check_matches(feature, value)


def test_singular_and_plural_follow_the_shown_number() -> None:
    assert render("missed_submissions", 1.0) == "1 submission missed so far"
    assert render("missed_submissions", 2.0) == "2 submissions missed so far"
    assert render("missed_submissions", 0.0) == "0 submissions missed so far"
    assert render("classes_held", 1.0).startswith("1 class held")


def test_text_never_judges_the_value() -> None:
    banned = re.compile(r"\b(risk|poor|low|high|bad|fail\w*|good|score)\b")
    for feature in FEATURE_NAMES:
        text = render(feature, 5.0).lower()
        assert not banned.search(text), text


def test_missing_value_and_unknown_feature_are_refused() -> None:
    with pytest.raises(ValueError):
        render("attendance_rate", float("nan"))
    with pytest.raises(KeyError):
        render("gender", 1.0)
