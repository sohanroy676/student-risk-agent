from datetime import date

import pandas as pd

from app.features.snapshot import FEATURE_NAMES
from app.ml.card import markdown_table, render_card
from app.ml.fairness import PROTECTED
from app.ml.gate import GateResult, SignOff

WEEKLY = pd.DataFrame({"week": [4, 8], "auc_cal": [0.701, 0.77], "ece": [0.02, float("nan")]})
GAPS = pd.DataFrame(
    {"attribute": ["gender", "region"], "recall_gap": [0.005, 0.105], "assessed": [True, True]}
)
GROUPS = pd.DataFrame(
    {
        "attribute": ["gender", "gender", "region"],
        "group": ["F", "M", "North|West"],
        "n": [100, 200, 5],
        "reliable": [True, True, False],
    }
)


def card(result: GateResult, sign_off: SignOff | None = None) -> str:
    return render_card(
        model_name="calibrated lgbm",
        generated_on=date(2026, 10, 28),
        trained_on="2013",
        tested_on="2014",
        weekly=WEEKLY,
        gaps=GAPS,
        groups=GROUPS,
        flag_rule="top 20% by score",
        result=result,
        sign_off=sign_off,
    )


def test_card_has_every_section_and_the_numbers() -> None:
    text = card(GateResult(True, (), (), (), None))
    for heading in (
        "# Model card",
        "## Data",
        "## Features",
        "## Results by week",
        "## Fairness",
        "## Promotion gate",
        "## Known limits",
    ):
        assert heading in text
    assert "| 4 | 0.701 | 0.020 |" in text
    assert "| 8 | 0.770 | n/a |" in text  # a missing number is shown as n/a, never as 0
    assert "flagged: top 20% by score" in text
    assert all(name in text for name in FEATURE_NAMES)
    assert "Not used as features" in text and all(name in text for name in PROTECTED)


def test_card_lists_only_reliable_groups_in_the_group_table() -> None:
    groups_part = (
        card(GateResult(True, (), (), (), None)).split("### Groups")[1].split("## Promotion")[0]
    )
    assert "| gender | F |" in groups_part
    assert "North" not in groups_part


def test_card_states_blocks_hard_failures_and_sign_off() -> None:
    blocked = card(GateResult(False, ("gap_high:region",), ("unassessed:gender",), (), None))
    assert "Blocked." in blocked and "gap_high:region" in blocked and "unassessed:gender" in blocked

    sign = SignOff("A. Dean", "pilot only", frozenset({"gap_high:region"}))
    promoted = card(
        GateResult(True, ("gap_high:region",), (), ("gap_high:region",), "A. Dean"), sign
    )
    assert "Promoted with sign-off by A. Dean." in promoted
    assert "Sign-off reason: pilot only" in promoted


def test_markdown_table_escapes_pipes_and_formats_booleans() -> None:
    table = markdown_table(pd.DataFrame({"group": ["a|b"], "ok": [True]}))
    assert "a\\|b" in table and "| yes |" in table
