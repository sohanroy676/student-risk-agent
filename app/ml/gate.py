"""Promotion gate: decides whether a candidate model may replace the current one.

A candidate is blocked by any of
- `auc_lower`: its week-4 AUC is below the current model's (skipped when there is no current),
- `ece_high`: calibration error above 0.05,
- `gap_high:<attribute>`: a recall gap between groups above 0.10.

A named sign-off may override exactly the blocks it lists. Missing numbers and attributes that
could not be assessed are never overridable: the gate cannot judge what it cannot see.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

ECE_LIMIT = 0.05
RECALL_GAP_LIMIT = 0.10


@dataclass(frozen=True)
class Metrics:
    """What the gate looks at. `recall_gaps` maps attribute to gap; NaN means not assessed."""

    auc_week4: float
    ece: float
    recall_gaps: Mapping[str, float]


@dataclass(frozen=True)
class SignOff:
    """A person's recorded decision to accept specific blocks."""

    name: str
    reason: str
    covers: frozenset[str]

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.reason.strip():
            raise ValueError("a sign-off needs a name and a reason")
        if not self.covers:
            raise ValueError("a sign-off must list the blocks it covers")


@dataclass(frozen=True)
class GateResult:
    passed: bool
    blocks: tuple[str, ...]  # soft blocks that applied (overridable)
    hard_failures: tuple[str, ...]  # missing or unassessable; never overridable
    overridden: tuple[str, ...]  # soft blocks the sign-off covered
    signed_off_by: str | None

    @property
    def unresolved(self) -> tuple[str, ...]:
        return tuple(b for b in self.blocks if b not in self.overridden)


def _missing(value: float | None) -> bool:
    return value is None or math.isnan(value)


def check(
    candidate: Metrics, current: Metrics | None, sign_off: SignOff | None = None
) -> GateResult:
    hard: list[str] = []
    soft: list[str] = []

    if _missing(candidate.auc_week4):
        hard.append("missing:auc_week4")
    elif current is not None and not _missing(current.auc_week4):
        if candidate.auc_week4 < current.auc_week4:
            soft.append("auc_lower")
    elif current is not None:
        hard.append("missing:current_auc_week4")

    if _missing(candidate.ece):
        hard.append("missing:ece")
    elif candidate.ece > ECE_LIMIT:
        soft.append("ece_high")

    if not candidate.recall_gaps:
        hard.append("missing:recall_gaps")
    for attribute, gap in sorted(candidate.recall_gaps.items()):
        if _missing(gap):
            hard.append(f"unassessed:{attribute}")
        elif gap > RECALL_GAP_LIMIT:
            soft.append(f"gap_high:{attribute}")

    covered = tuple(b for b in soft if sign_off is not None and b in sign_off.covers)
    passed = not hard and len(covered) == len(soft)
    return GateResult(
        passed=passed,
        blocks=tuple(soft),
        hard_failures=tuple(hard),
        overridden=covered,
        signed_off_by=sign_off.name if sign_off is not None and covered else None,
    )
