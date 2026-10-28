from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.features.snapshot import FEATURE_NAMES
from app.ml.baseline import weekly_matrix
from app.ml.calibrate import CalibratedModel, fit_calibrated
from app.ml.explain import contributions, top_reasons
from app.ml.reasons import render
from data.synthetic import generator
from data.synthetic.frames import to_core_tables

AS_OF = date(2025, 1, 1)

World = tuple[CalibratedModel, pd.DataFrame]


@pytest.fixture(scope="module")
def world() -> World:
    """Production model fitted on the synthetic term (two fake presentations), plus test rows."""
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
    starts = cohort.loc[features.index[train], "term_start"]
    return fit_calibrated(features[train], y[train], starts), features[~train]


def test_contributions_add_up_to_the_models_raw_margin(world: World) -> None:
    fitted, test = world
    booster = fitted.model.booster_
    base = np.asarray(booster.predict(test, pred_contrib=True))[:, -1]
    margin = np.asarray(booster.predict(test, raw_score=True))
    shap = contributions(fitted, test)
    assert list(shap.columns) == list(FEATURE_NAMES)
    np.testing.assert_allclose(shap.sum(axis=1) + base, margin, atol=1e-6)


def test_every_reason_matches_its_feature_value_and_is_well_formed(world: World) -> None:
    fitted, test = world
    shap = contributions(fitted, test)
    result = top_reasons(shap, test, AS_OF)
    assert set(result) == set(test.index)
    total = 0
    fact_ids: set[str] = set()
    for ref, reasons in result.items():
        assert len(reasons) <= 3
        ordered = sorted((r.contribution for r in reasons), reverse=True)
        assert [r.contribution for r in reasons] == ordered
        for r in reasons:
            total += 1
            assert r.value == test.at[ref, r.feature]  # exact, not rounded
            assert r.contribution == shap.at[ref, r.feature] > 0
            assert r.text == render(r.feature, test.at[ref, r.feature])
            assert r.fact_id == f"{ref}/{r.feature}/2025-01-01"
            fact_ids.add(r.fact_id)
    assert total > 0
    assert len(fact_ids) == total  # no two reasons share a fact_id


def test_features_without_a_value_are_never_reasons(world: World) -> None:
    fitted, test = world
    blanked = test.copy()
    blanked[:] = np.nan
    shap = contributions(fitted, blanked)
    assert all(not reasons for reasons in top_reasons(shap, blanked, AS_OF).values())


def test_only_positive_contributions_and_k_are_respected() -> None:
    columns = ["attendance_rate", "classes_held", "prior_attempts"]
    features = pd.DataFrame([[0.5, 2.0, 1.0]], columns=columns, index=["c1"])
    shap = pd.DataFrame([[-0.4, 0.3, 0.2]], columns=features.columns, index=features.index)
    one = top_reasons(shap, features, AS_OF, k=1)["c1"]
    assert [r.feature for r in one] == ["classes_held"]
    both = top_reasons(shap, features, AS_OF, k=5)["c1"]
    assert [r.feature for r in both] == ["classes_held", "prior_attempts"]


def test_bad_input_is_refused(world: World) -> None:
    fitted, test = world
    shap = contributions(fitted, test)
    with pytest.raises(ValueError, match="k must"):
        top_reasons(shap, test, AS_OF, k=0)
    with pytest.raises(ValueError, match="same rows"):
        top_reasons(shap.iloc[1:], test, AS_OF)
    with pytest.raises(ValueError, match="do not match"):
        contributions(fitted, test[list(reversed(test.columns))])
    dup = pd.concat([test.head(2), test.head(2)])
    with pytest.raises(ValueError, match="duplicate"):
        top_reasons(contributions(fitted, dup), dup, AS_OF)
