import pytest

from app.cases.drafts import (
    FIRST_CONTACT,
    FOLLOW_UP,
    MAX_LENGTH,
    InvalidMessage,
    check_message,
    template_message,
)


def test_the_templates_pass_their_own_check() -> None:
    for text in (FIRST_CONTACT, FOLLOW_UP):
        assert check_message(text) == text
        assert len(text) < MAX_LENGTH


def test_first_contact_for_cycle_one_and_follow_up_after() -> None:
    assert template_message(1) == FIRST_CONTACT
    assert template_message(2) == template_message(3) == FOLLOW_UP != FIRST_CONTACT


def test_the_message_is_trimmed() -> None:
    assert check_message("  Hello there \n") == "Hello there"


@pytest.mark.parametrize("message", ["", "   ", "\n\t "])
def test_an_empty_message_is_refused(message: str) -> None:
    with pytest.raises(InvalidMessage):
        check_message(message)


def test_the_length_limit_is_exact() -> None:
    assert check_message("a" * MAX_LENGTH) == "a" * MAX_LENGTH
    with pytest.raises(InvalidMessage):
        check_message("a" * (MAX_LENGTH + 1))


@pytest.mark.parametrize("message", ["bad\x00byte", "esc\x1b[0m", "bell\x07", "del\x7f"])
def test_control_characters_are_refused(message: str) -> None:
    with pytest.raises(InvalidMessage):
        check_message(message)


def test_newlines_are_allowed() -> None:
    assert check_message("two\nlines") == "two\nlines"


@pytest.mark.parametrize(
    "message",
    [
        "You are at risk of failing",
        "your RISK is high",
        "Your score is 0.8",
        "you were scored low",
        "You are in the red band",
        "Red Zone student",
        "red flag raised",
        "the model predicts you will fail",
        "a prediction says so",
        "you have been flagged",
        "Amber status",
        "probability of dropout",
        "risky behaviour",
        "high-risk",
    ],
)
def test_banned_terms_are_refused_in_any_case_and_form(message: str) -> None:
    with pytest.raises(InvalidMessage):
        check_message(message)


@pytest.mark.parametrize(
    "message",
    ["I will be in my office on Friday", "The bandwidth is fine", "Reduce the credit load?"],
)
def test_ordinary_words_that_merely_contain_a_banned_stem_are_allowed(message: str) -> None:
    assert check_message(message) == message
