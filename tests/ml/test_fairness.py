import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.features.snapshot import FEATURE_NAMES
from app.ml import fairness
from app.ml.baseline import weekly_matrix
from app.ml.calibrate import fit_calibrated
from app.ml.fairness import (
    PROTECTED,
    fairness_report,
    flag_top,
    group_table,
    recall_gaps,
)
from data.synthetic import generator
from data.synthetic.frames import to_core_tables


def toy() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Group A: recall 0.5; group B: recall 1.0. Each group has 2 positives and 2 negatives."""
    index = pd.RangeIndex(8)
    attributes = pd.DataFrame({"gender": list("AAAABBBB")}, index=index)
    y = pd.Series([1, 1, 0, 0, 1, 1, 0, 0], index=index)
    flagged = pd.Series([1, 0, 1, 0, 1, 1, 0, 0], index=index).astype(bool)
    return attributes, y, flagged


# --- flag_top ---


def test_flag_top_flags_the_best_scored_fraction() -> None:
    score = pd.Series(np.arange(100.0))
    flagged = flag_top(score, 0.2)
    assert flagged.sum() == 20
    assert flagged[80:].all() and not flagged[:80].any()


def test_flag_top_flags_every_row_tied_at_the_cutoff_and_at_least_one() -> None:
    assert flag_top(pd.Series([0.9, 0.5, 0.5, 0.5, 0.1]), 0.4).tolist() == [
        True,
        True,
        True,
        True,
        False,
    ]
    assert flag_top(pd.Series([0.1, 0.9]), 0.01).tolist() == [False, True]


@pytest.mark.parametrize("frac", [0, -1, 1.2])
def test_flag_top_rejects_bad_fraction(frac: float) -> None:
    with pytest.raises(ValueError):
        flag_top(pd.Series([0.1, 0.2]), frac)


def test_flag_top_rejects_empty_and_nan_scores() -> None:
    with pytest.raises(ValueError):
        flag_top(pd.Series([], dtype=float))
    with pytest.raises(ValueError):
        flag_top(pd.Series([0.1, np.nan]))


# --- group_table / recall_gaps ---


def test_group_metrics_match_hand_computed_values() -> None:
    attributes, y, flagged = toy()
    table = group_table(attributes, y, flagged, min_group_size=4, min_positives=2)
    a, b = (table[table["group"] == g].iloc[0] for g in "AB")
    assert (a["n"], a["positives"], a["at_risk_rate"]) == (4, 2, 0.5)
    assert (a["recall"], a["selection_rate"], a["precision"], a["false_positive_rate"]) == (
        0.5,
        0.5,
        0.5,
        0.5,
    )
    assert (b["recall"], b["selection_rate"], b["precision"], b["false_positive_rate"]) == (
        1.0,
        0.5,
        1.0,
        0.0,
    )
    assert table["reliable"].all()


def test_recall_gap_names_the_groups_and_applies_the_limit() -> None:
    attributes, y, flagged = toy()
    gaps = recall_gaps(group_table(attributes, y, flagged, min_group_size=4, min_positives=2))
    row = gaps.iloc[0]
    assert row["recall_gap"] == pytest.approx(0.5)
    assert (row["lowest_recall_group"], row["highest_recall_group"]) == ("A", "B")
    assert bool(row["assessed"]) and not bool(row["within_limit"])
    loose = recall_gaps(group_table(attributes, y, flagged, 4, 2), limit=0.6)
    assert bool(loose.iloc[0]["within_limit"])


def test_recall_matches_an_independent_calculation_on_random_data() -> None:
    rng = np.random.default_rng(0)
    n = 3000
    index = pd.RangeIndex(n)
    attributes = pd.DataFrame(
        {"gender": rng.choice(["F", "M"], n), "age_band": rng.choice(["0-35", "35-55", "55<="], n)},
        index=index,
    )
    y = pd.Series(rng.random(n) < 0.3, index=index)
    flagged = pd.Series(rng.random(n) < (0.2 + 0.3 * y), index=index)
    table = group_table(attributes, y, flagged)
    for row in table.itertuples():
        mask = attributes[row.attribute] == row.group
        positives = y & mask
        assert row.recall == pytest.approx((flagged & positives).sum() / positives.sum())
        assert row.selection_rate == pytest.approx(flagged[mask].mean())


def test_small_groups_are_listed_but_left_out_of_the_gap() -> None:
    n = 400
    index = pd.RangeIndex(n)
    group = ["big1"] * 190 + ["big2"] * 190 + ["tiny"] * 20
    y = pd.Series([True, False] * (n // 2), index=index)
    flagged = pd.Series(False, index=index)
    flagged[:190] = y[:190]  # big1 recall 1.0
    table = group_table(pd.DataFrame({"region": group}, index=index), y, flagged)
    assert table.set_index("group")["reliable"].to_dict() == {
        "big1": True,
        "big2": True,
        "tiny": False,
    }
    gaps = recall_gaps(table)
    assert gaps.iloc[0]["recall_gap"] == pytest.approx(1.0)
    assert gaps.iloc[0]["reliable_groups"] == 2


def test_a_group_without_positives_has_nan_recall_not_zero() -> None:
    index = pd.RangeIndex(300)
    attributes = pd.DataFrame({"gender": ["A"] * 150 + ["B"] * 150}, index=index)
    y = pd.Series([True] * 150 + [False] * 150, index=index)
    table = group_table(attributes, y, y.copy())
    assert np.isnan(table.set_index("group").loc["B", "recall"])


def test_an_attribute_that_cannot_be_assessed_does_not_pass_by_default() -> None:
    attributes, y, flagged = toy()  # groups of 4 are below the default minimum size
    gaps = recall_gaps(group_table(attributes, y, flagged))
    row = gaps.iloc[0]
    assert np.isnan(row["recall_gap"])
    assert not bool(row["assessed"]) and not bool(row["within_limit"])


def test_missing_attribute_values_form_their_own_group() -> None:
    attributes, y, flagged = toy()
    attributes.loc[0, "gender"] = None
    table = group_table(attributes, y, flagged, 1, 1)
    assert "unknown" in set(table["group"])
    assert table["n"].sum() == 8


def test_only_known_protected_columns_and_aligned_rows_are_accepted() -> None:
    attributes, y, flagged = toy()
    with pytest.raises(ValueError, match="not protected attributes"):
        group_table(attributes.assign(final_result="Pass"), y, flagged)
    with pytest.raises(ValueError, match="same index"):
        group_table(attributes, y.iloc[::-1].reset_index(drop=True).iloc[1:], flagged)


# --- evaluation only: attributes cannot be model inputs ---


def test_no_protected_attribute_is_a_model_feature() -> None:
    assert not set(PROTECTED) & set(FEATURE_NAMES)
    assert not {"student_id", "term_start"} & set(FEATURE_NAMES)


def test_report_on_real_model_scores_leaves_the_scores_alone() -> None:
    data = generator.generate(seed=11)
    ids = list(range(1, generator.N_STUDENTS + 1))
    start = pd.Timestamp(generator.TERM_START)
    kind = pd.Series([i % 3 for i in ids], index=pd.Index(ids, name="student_id"))
    cohort = pd.DataFrame(
        {
            "term_start": kind.map({0: start, 1: start + pd.Timedelta(days=1), 2: start}),
            "at_risk": [i in data.struggling_ids for i in ids],
            "split": kind.map({0: "train", 1: "train", 2: "test"}),
            "unregistered_on": pd.NaT,
        },
        index=kind.index,
    )
    features, y, split = weekly_matrix(to_core_tables(data), cohort, 8)
    train = split == "train"
    fitted = fit_calibrated(
        features[train], y[train], cohort.loc[features.index[train], "term_start"]
    )
    assert not set(PROTECTED) & set(fitted.model.booster_.feature_name())

    score = pd.Series(fitted.raw_score(features[~train]), index=features.index[~train])
    before = score.copy()
    rng = np.random.default_rng(1)
    attributes = pd.DataFrame({"gender": rng.choice(["F", "M"], len(score))}, index=score.index)
    table, gaps = fairness_report(
        attributes, y[~train], score, 0.2, min_group_size=10, min_positives=2
    )
    pd.testing.assert_series_equal(score, before)
    assert set(table["group"]) == {"F", "M"}
    assert gaps.iloc[0]["recall_gap"] >= 0


# --- CLI ---


def test_cli_fails_clearly_when_there_is_only_one_training_presentation(
    oulad_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["fairness", "--oulad", str(oulad_dir)])
    with pytest.raises(ValueError, match="two training presentations"):
        fairness.main()
