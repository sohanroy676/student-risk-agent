"""Case-engine tuning knobs in one place.

Every number here is an untuned default chosen before real college data; the red/amber cut-offs
are calibrated probabilities (activeContext, 2026-10-28). Change them here, not in the logic.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CaseConfig:
    # Hysteresis: a band is entered at `*_enter` and left only below `*_exit`.
    red_enter: float = 0.50
    red_exit: float = 0.45
    amber_enter: float = 0.30
    amber_exit: float = 0.25
    # A fast rise opens a case even before the student is red (amber or above required).
    rise_window_days: int = 7
    rise_delta: float = 0.15
    # Rate limit and re-open cooldown.
    max_new_per_mentor_per_night: int = 3
    reopen_cooldown_days: int = 28
    severe: float = 0.70
    # Timers, in days.
    draft_due_days: int = 1
    review_due_days: int = 3
    followup_days: int = 7
    max_cycles: int = 2

    def __post_init__(self) -> None:
        ordered = 0 < self.amber_exit < self.amber_enter <= self.red_exit < self.red_enter <= 1
        if not ordered:
            raise ValueError("need 0 < amber_exit < amber_enter <= red_exit < red_enter <= 1")
        if not self.red_enter <= self.severe <= 1:
            raise ValueError("severe must lie between red_enter and 1")
        if self.max_new_per_mentor_per_night < 1 or self.max_cycles < 1:
            raise ValueError("caps must be at least 1")
        if min(self.rise_window_days, self.followup_days, self.draft_due_days) < 1:
            raise ValueError("day counts must be at least 1")
        if not 0 < self.rise_delta <= 1 or self.reopen_cooldown_days < 0:
            raise ValueError("invalid rise_delta or cooldown")
