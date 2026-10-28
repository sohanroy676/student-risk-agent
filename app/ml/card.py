"""Markdown model card for a release: what the model is, how it scored, who it was checked on.

Everything in the card is an aggregate; no student-level data is written.
"""

from datetime import date

import pandas as pd

from app.features.snapshot import FEATURE_NAMES
from app.ml.fairness import PROTECTED
from app.ml.gate import ECE_LIMIT, RECALL_GAP_LIMIT, GateResult, SignOff

LIMITS = (
    "OULAD has no attendance or fee data, so those features are empty on this run.",
    "The original AUC targets (0.72 at week 1, 0.86 at week 8) are not reachable on OULAD; "
    "they were relaxed to 0.68 and 0.79 and remain the goal on the college's own data.",
    "The top-10% precision target is capped at 0.70 where the base rate makes 2x unreachable.",
    "The fairness table flags by the rule in its heading. The red band rule leaves out hysteresis "
    "and the per-mentor nightly cap, and amber cases are not audited.",
    "Reasons describe feature values only; they do not say which direction is concerning.",
    "The model supports a mentor's judgement. It makes no automated decisions, and scores are "
    "never shown to students, parents or faculty.",
)


def _cell(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return "n/a" if value != value else f"{value:.3f}"
    return str(value).replace("|", "\\|")


def markdown_table(frame: pd.DataFrame) -> str:
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "| " + " | ".join("---" for _ in frame.columns) + " |"
    rows = [
        "| " + " | ".join(_cell(v) for v in row) + " |" for row in frame.itertuples(index=False)
    ]
    return "\n".join([header, rule, *rows])


def render_card(
    *,
    model_name: str,
    generated_on: date,
    trained_on: str,
    tested_on: str,
    weekly: pd.DataFrame,
    gaps: pd.DataFrame,
    groups: pd.DataFrame,
    flag_rule: str,
    result: GateResult,
    sign_off: SignOff | None = None,
) -> str:
    reliable = groups[groups["reliable"]].drop(columns="reliable")
    if result.passed and result.signed_off_by:
        verdict = f"Promoted with sign-off by {result.signed_off_by}."
    elif result.passed:
        verdict = "Promoted."
    else:
        verdict = "Blocked."
    gate_lines = [
        f"- Result: **{verdict}**",
        f"- Limits: ECE at most {ECE_LIMIT}, recall gap at most {RECALL_GAP_LIMIT}, "
        "week-4 AUC not lower than the current model.",
        f"- Blocks: {', '.join(result.blocks) or 'none'}",
        f"- Not overridable: {', '.join(result.hard_failures) or 'none'}",
    ]
    if sign_off is not None and result.overridden:
        gate_lines += [
            f"- Overridden by {sign_off.name}: {', '.join(result.overridden)}",
            f"- Sign-off reason: {sign_off.reason}",
        ]
    sections = [
        f"# Model card: {model_name}",
        f"Generated {generated_on.isoformat()}.",
        "## Purpose\nNightly early-warning score for a mentor, with three plain reasons per "
        "student. A calibrated LightGBM model, fitted once per checkpoint week.",
        f"## Data\nTrained on {trained_on}; tested on {tested_on}. The calibration split is the "
        "latest training presentation; the test year is never used to fit or calibrate.",
        f"## Features\n{len(FEATURE_NAMES)} features, each built only from data dated on or "
        "before the checkpoint date: " + ", ".join(FEATURE_NAMES) + ".",
        "## Protected attributes\nNot used as features. Kept separately for this audit only: "
        + ", ".join(PROTECTED)
        + ".",
        "## Results by week (test year)\n" + markdown_table(weekly),
        f"## Fairness (week 4, flagged: {flag_rule})\n"
        "Recall gap is the largest difference in recall between groups of at least 100 "
        "students and 20 positives.\n\n" + markdown_table(gaps),
        "### Groups\n" + markdown_table(reliable),
        "## Promotion gate\n" + "\n".join(gate_lines),
        "## Known limits\n" + "\n".join(f"- {line}" for line in LIMITS),
    ]
    return "\n\n".join(sections) + "\n"
