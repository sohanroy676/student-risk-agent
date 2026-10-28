"""Risk bands with hysteresis."""

import math
from enum import StrEnum

from app.cases.config import CaseConfig


class Band(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


def check_probability(p: float) -> float:
    """A NaN or out-of-range score must stop the run, never quietly become green."""
    if (
        isinstance(p, bool)
        or not isinstance(p, int | float)
        or math.isnan(p)
        or not 0.0 <= p <= 1.0
    ):
        raise ValueError(f"probability must be a number in [0, 1], got {p!r}")
    return float(p)


def next_band(previous: Band | None, p: float, cfg: CaseConfig) -> Band:
    """Tonight's band: enter at the `enter` cut-off, stay until below the `exit` cut-off."""
    p = check_probability(p)
    if p >= cfg.red_enter or (previous is Band.RED and p >= cfg.red_exit):
        return Band.RED
    amber_floor = cfg.amber_exit if previous in (Band.AMBER, Band.RED) else cfg.amber_enter
    return Band.AMBER if p >= amber_floor else Band.GREEN


def rising_fast(p: float, earlier: float | None, band: Band, cfg: CaseConfig) -> bool:
    """Up by `rise_delta` or more over the window, and already at least amber."""
    if earlier is None or band is Band.GREEN:
        return False
    return p - check_probability(earlier) >= cfg.rise_delta
