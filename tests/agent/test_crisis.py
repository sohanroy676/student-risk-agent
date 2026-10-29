import pytest

from app.agent.crisis import is_crisis, normalise
from app.cases.drafts import FIRST_CONTACT, FOLLOW_UP


@pytest.mark.parametrize(
    "note",
    [
        "Student said they want to die",
        "talked about suicide in class",
        "Self-harm marks on arm",
        "SELF HARM",
        "mentioned hurting themselves",
        "says she wishes she was dead",
        "taking an overdose",
        "unsafe at home",
        "being abused by a relative",
        "ended up saying they might kill himself",
        "s​uicide",  # zero-width character inside the word
        "ｓｕｉｃｉｄｅ",  # full-width letters
        "su­icide",  # soft hyphen
    ],
)
def test_crisis_wording_is_found(note: str) -> None:
    assert is_crisis([note])


@pytest.mark.parametrize(
    "note",
    [
        "",
        "Missed three classes this week",
        "Marks dropped in the maths quiz",
        "Seems tired and quiet",
        "Late fee instalment",
        "Died laughing at the joke",  # 'died' alone is not a crisis term
    ],
)
def test_ordinary_notes_are_not(note: str) -> None:
    assert not is_crisis([note])


def test_any_one_of_several_texts_is_enough() -> None:
    assert is_crisis(["fine", "all good", "talked about suicide"])
    assert not is_crisis([])


def test_the_templates_are_not_crisis_wording() -> None:
    assert not is_crisis([FIRST_CONTACT, FOLLOW_UP])


def test_normalise_drops_invisible_characters_and_folds_width() -> None:
    assert normalise("a​b﻿c") == "abc"
    assert normalise("ＡＢ") == "AB"
