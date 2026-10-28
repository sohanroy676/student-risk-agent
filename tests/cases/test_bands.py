import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.cases.bands import Band, check_probability, next_band, rising_fast
from app.cases.config import CaseConfig

CFG = CaseConfig()


@pytest.mark.parametrize(
    ("previous", "p", "expected"),
    [
        (None, 0.0, Band.GREEN),
        (None, 0.29, Band.GREEN),
        (None, 0.30, Band.AMBER),
        (None, 0.49, Band.AMBER),
        (None, 0.50, Band.RED),
        (None, 1.0, Band.RED),
        (Band.GREEN, 0.27, Band.GREEN),  # entering amber needs the higher cut-off
        (Band.AMBER, 0.27, Band.AMBER),  # staying amber only needs the lower one
        (Band.AMBER, 0.24, Band.GREEN),
        (Band.AMBER, 0.47, Band.AMBER),  # entering red needs 0.50
        (Band.RED, 0.47, Band.RED),  # staying red only needs 0.45
        (Band.RED, 0.44, Band.AMBER),
        (Band.RED, 0.20, Band.GREEN),  # a big fall skips amber
    ],
)
def test_band_table(previous: Band | None, p: float, expected: Band) -> None:
    assert next_band(previous, p, CFG) is expected


@given(st.lists(st.floats(min_value=0.451, max_value=0.499), min_size=1, max_size=30))
def test_wobble_inside_the_red_margin_never_leaves_red(ps: list[float]) -> None:
    band = Band.RED
    for p in ps:
        band = next_band(band, p, CFG)
        assert band is Band.RED


@given(st.lists(st.floats(min_value=0.251, max_value=0.449), min_size=1, max_size=30))
def test_wobble_inside_the_amber_margin_never_changes_amber(ps: list[float]) -> None:
    band = Band.AMBER
    for p in ps:
        band = next_band(band, p, CFG)
        assert band is Band.AMBER


@given(st.sampled_from([None, *Band]), st.floats(min_value=0, max_value=1))
def test_a_higher_score_never_gives_a_lower_band(previous: Band | None, p: float) -> None:
    order = {Band.GREEN: 0, Band.AMBER: 1, Band.RED: 2}
    assert order[next_band(previous, p, CFG)] <= order[next_band(previous, min(1.0, p + 0.1), CFG)]


@pytest.mark.parametrize("bad", [float("nan"), -0.01, 1.01, float("inf"), "0.5", None, True])
def test_bad_probabilities_raise(bad: object) -> None:
    with pytest.raises(ValueError, match="probability"):
        check_probability(bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="probability"):
        next_band(None, bad, CFG)  # type: ignore[arg-type]


def test_rising_fast() -> None:
    assert rising_fast(0.40, 0.25, Band.AMBER, CFG)  # exactly +0.15
    assert not rising_fast(0.39, 0.25, Band.AMBER, CFG)
    assert not rising_fast(0.20, 0.0, Band.GREEN, CFG)  # a big rise inside green is ignored
    assert not rising_fast(0.60, None, Band.RED, CFG)  # no earlier score, no rise


@pytest.mark.parametrize(
    "kwargs",
    [
        {"amber_enter": 0.2},  # below amber_exit
        {"red_exit": 0.6},  # above red_enter
        {"red_enter": 1.5},
        {"severe": 0.4},
        {"max_new_per_mentor_per_night": 0},
        {"max_cycles": 0},
        {"followup_days": 0},
        {"rise_delta": 0},
        {"reopen_cooldown_days": -1},
    ],
)
def test_nonsense_config_is_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        CaseConfig(**kwargs)  # type: ignore[arg-type]
