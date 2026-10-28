from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from app.ml.baseline import WEEKS, evaluate_by_week, weekly_matrix
from data.synthetic import generator
from data.synthetic.frames import to_core_tables

World = tuple[generator.SyntheticData, pd.DataFrame]


@pytest.fixture(scope="module")
def world() -> World:
    data = generator.generate(seed=11)
    ids = range(1, generator.N_STUDENTS + 1)
    cohort = pd.DataFrame(
        {
            "term_start": pd.Timestamp(generator.TERM_START),
            "at_risk": [i in data.struggling_ids for i in ids],
            "split": ["train" if i % 2 else "test" for i in ids],
            "unregistered_on": pd.NaT,
        },
        index=pd.Index(list(ids), name="student_id"),
    )
    return data, cohort


def test_weekly_table_shape_and_planted_signal(world: World) -> None:
    data, cohort = world
    result = evaluate_by_week(to_core_tables(data), cohort)
    assert result["week"].tolist() == list(WEEKS)
    assert (result["n_train"] + result["n_test"] == generator.N_STUDENTS).all()
    late = result.set_index("week").loc[8]
    assert late["auc_logreg"] > 0.9
    assert late["auc_rules"] > 0.8
    assert result["auc_logreg"].between(0, 1).all()


def test_shuffled_labels_give_chance_level_auc(world: World) -> None:
    data, cohort = world
    shuffled = cohort.copy()
    shuffled["at_risk"] = np.random.default_rng(0).permutation(cohort["at_risk"].to_numpy())
    result = evaluate_by_week(to_core_tables(data), shuffled, weeks=[8])
    assert 0.3 < result.loc[0, "auc_logreg"] < 0.7


def test_model_never_sees_test_labels(world: World) -> None:
    data, cohort = world
    flipped = cohort.copy()
    test = flipped["split"] == "test"
    flipped.loc[test, "at_risk"] = ~flipped.loc[test, "at_risk"]
    tables = to_core_tables(data)
    normal = evaluate_by_week(tables, cohort, weeks=[6]).loc[0]
    inverted = evaluate_by_week(tables, flipped, weeks=[6]).loc[0]
    assert inverted["auc_logreg"] == pytest.approx(1 - normal["auc_logreg"])
    assert inverted["auc_rules"] == pytest.approx(1 - normal["auc_rules"])


def test_students_who_already_left_are_excluded(world: World) -> None:
    data, cohort = world
    week = 4
    as_of = cohort["term_start"].iloc[0] + pd.Timedelta(days=7 * week)
    left = cohort.copy()
    left.loc[1, "unregistered_on"] = as_of  # leaves on as_of itself: out
    left.loc[2, "unregistered_on"] = as_of + pd.Timedelta(days=1)  # leaves the day after: in
    left.loc[3, "unregistered_on"] = as_of - pd.Timedelta(days=30)  # long gone: out
    features, y, split = weekly_matrix(to_core_tables(data), left, week)
    assert 1 not in features.index
    assert 3 not in features.index
    assert 2 in features.index
    assert len(features) == len(y) == len(split) == generator.N_STUDENTS - 2


def test_single_class_test_set_gives_nan_not_a_crash(world: World) -> None:
    data, cohort = world
    one_class = cohort.copy()
    one_class.loc[one_class["split"] == "test", "at_risk"] = False
    result = evaluate_by_week(to_core_tables(data), one_class, weeks=[4])
    assert np.isnan(result.loc[0, "auc_logreg"])
    assert np.isnan(result.loc[0, "auc_rules"])


def test_as_of_follows_each_students_own_term_start(world: World) -> None:
    data, cohort = world
    tables = to_core_tables(data)
    shifted = cohort.copy()
    first = shifted.index[:100]
    shifted.loc[first, "term_start"] += pd.Timedelta(days=21)
    base, _, _ = weekly_matrix(tables, cohort, 5)
    moved, _, _ = weekly_matrix(tables, shifted, 5)
    # A later term start puts as_of later on the calendar, so only those students see more data.
    assert (moved.loc[first, "classes_held"] > base.loc[first, "classes_held"]).all()
    pd.testing.assert_frame_equal(moved.drop(index=first), base.drop(index=first))


def _drop_split(c: pd.DataFrame) -> pd.DataFrame:
    return c.drop(columns=["split"])


def _bad_split(c: pd.DataFrame) -> pd.DataFrame:
    return c.assign(split="val")


def _duplicate_id(c: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([c, c.iloc[:1]])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_drop_split, "missing columns"),
        (_bad_split, "train"),
        (_duplicate_id, "duplicate"),
    ],
)
def test_invalid_cohorts_are_rejected(
    world: World, mutate: Callable[[pd.DataFrame], pd.DataFrame], message: str
) -> None:
    data, cohort = world
    with pytest.raises(ValueError, match=message):
        evaluate_by_week(to_core_tables(data), mutate(cohort), weeks=[1])


def test_cohort_with_nobody_registered_raises(world: World) -> None:
    data, cohort = world
    gone = cohort.assign(unregistered_on=pd.Timestamp(generator.TERM_START))
    with pytest.raises(ValueError, match="no registered students"):
        evaluate_by_week(to_core_tables(data), gone, weeks=[1])


def test_default_evaluates_only_logistic_regression(world: World) -> None:
    data, cohort = world
    result = evaluate_by_week(to_core_tables(data), cohort, weeks=[8])
    assert "auc_logreg" in result.columns
    assert "auc_lgbm" not in result.columns


def test_lightgbm_finds_the_planted_signal(world: World) -> None:
    data, cohort = world
    result = evaluate_by_week(to_core_tables(data), cohort, weeks=[8], models=["logreg", "lgbm"])
    assert result.loc[0, "auc_lgbm"] > 0.9


def test_lightgbm_on_shuffled_labels_is_chance_level(world: World) -> None:
    data, cohort = world
    shuffled = cohort.copy()
    shuffled["at_risk"] = np.random.default_rng(0).permutation(cohort["at_risk"].to_numpy())
    result = evaluate_by_week(to_core_tables(data), shuffled, weeks=[8], models=["lgbm"])
    assert 0.3 < result.loc[0, "auc_lgbm"] < 0.7


def test_lightgbm_never_sees_test_labels(world: World) -> None:
    data, cohort = world
    flipped = cohort.copy()
    test = flipped["split"] == "test"
    flipped.loc[test, "at_risk"] = ~flipped.loc[test, "at_risk"]
    tables = to_core_tables(data)
    normal = evaluate_by_week(tables, cohort, weeks=[6], models=["lgbm"]).loc[0]
    inverted = evaluate_by_week(tables, flipped, weeks=[6], models=["lgbm"]).loc[0]
    assert inverted["auc_lgbm"] == pytest.approx(1 - normal["auc_lgbm"])


def test_lightgbm_is_deterministic(world: World) -> None:
    data, cohort = world
    tables = to_core_tables(data)
    first = evaluate_by_week(tables, cohort, weeks=[4], models=["lgbm"])
    second = evaluate_by_week(tables, cohort, weeks=[4], models=["lgbm"])
    assert first.loc[0, "auc_lgbm"] == second.loc[0, "auc_lgbm"]


def test_unknown_model_name_is_rejected(world: World) -> None:
    data, cohort = world
    with pytest.raises(ValueError, match="unknown models"):
        evaluate_by_week(to_core_tables(data), cohort, models=["logreg", "xgboost"])


def test_single_class_training_gives_nan_for_every_model(world: World) -> None:
    data, cohort = world
    one_class = cohort.copy()
    one_class.loc[one_class["split"] == "train", "at_risk"] = False
    result = evaluate_by_week(to_core_tables(data), one_class, weeks=[8], models=["logreg", "lgbm"])
    assert result[["auc_logreg", "auc_lgbm"]].isna().all().all()
