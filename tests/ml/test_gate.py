import pytest

from app.ml.gate import Metrics, SignOff, check

GOOD = Metrics(auc_week4=0.74, ece=0.02, recall_gaps={"gender": 0.03, "age_band": 0.08})


def with_(base: Metrics = GOOD, **changes: object) -> Metrics:
    fields = {"auc_week4": base.auc_week4, "ece": base.ece, "recall_gaps": base.recall_gaps}
    return Metrics(**{**fields, **changes})  # type: ignore[arg-type]


def sign(*covers: str) -> SignOff:
    return SignOff("A. Dean", "accepted for pilot", frozenset(covers))


def test_a_good_candidate_passes_with_or_without_a_current_model() -> None:
    assert check(GOOD, None).passed
    assert check(GOOD, with_(auc_week4=0.70)).passed
    result = check(GOOD, GOOD)  # equal AUC is not lower
    assert result.passed and not result.blocks and result.signed_off_by is None


def test_lower_week4_auc_blocks() -> None:
    result = check(with_(auc_week4=0.739), GOOD)
    assert not result.passed and result.blocks == ("auc_lower",)


def test_ece_above_limit_blocks_and_the_limit_itself_passes() -> None:
    assert check(with_(ece=0.0501), None).blocks == ("ece_high",)
    assert check(with_(ece=0.05), None).passed


def test_group_recall_gap_above_limit_blocks_and_names_the_attribute() -> None:
    result = check(with_(recall_gaps={"gender": 0.03, "region": 0.101}), None)
    assert not result.passed and result.blocks == ("gap_high:region",)
    assert check(with_(recall_gaps={"region": 0.10}), None).passed


def test_all_blocks_are_reported_together() -> None:
    bad = Metrics(0.6, 0.2, {"a": 0.5, "b": 0.4})
    assert check(bad, GOOD).blocks == ("auc_lower", "ece_high", "gap_high:a", "gap_high:b")


def test_sign_off_overrides_only_the_blocks_it_lists() -> None:
    bad = Metrics(0.74, 0.02, {"region": 0.2, "age_band": 0.3})
    partial = check(bad, None, sign("gap_high:region"))
    assert not partial.passed
    assert partial.unresolved == ("gap_high:age_band",) and partial.overridden == (
        "gap_high:region",
    )
    full = check(bad, None, sign("gap_high:region", "gap_high:age_band"))
    assert full.passed and full.signed_off_by == "A. Dean" and not full.unresolved


def test_a_sign_off_for_blocks_that_do_not_apply_changes_nothing() -> None:
    result = check(GOOD, None, sign("ece_high"))
    assert result.passed and result.signed_off_by is None


@pytest.mark.parametrize(
    "metrics",
    [
        with_(auc_week4=float("nan")),
        with_(ece=float("nan")),
        with_(recall_gaps={}),
        with_(recall_gaps={"gender": float("nan")}),
    ],
)
def test_missing_or_unassessed_metrics_cannot_be_signed_off(metrics: Metrics) -> None:
    everything = sign(
        "auc_lower", "ece_high", "gap_high:gender", "missing:ece", "unassessed:gender"
    )
    result = check(metrics, None, everything)
    assert not result.passed and result.hard_failures


def test_current_model_without_an_auc_is_a_hard_failure() -> None:
    result = check(GOOD, with_(auc_week4=float("nan")), sign("auc_lower"))
    assert not result.passed and result.hard_failures == ("missing:current_auc_week4",)


def test_sign_off_needs_a_name_a_reason_and_a_scope() -> None:
    with pytest.raises(ValueError):
        SignOff("", "reason", frozenset({"ece_high"}))
    with pytest.raises(ValueError):
        SignOff("name", "  ", frozenset({"ece_high"}))
    with pytest.raises(ValueError):
        SignOff("name", "reason", frozenset())
