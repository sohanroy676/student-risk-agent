import numpy as np
import pandas as pd
import pytest

from app.ml import calibrate
from app.ml.baseline import WEEKS
from app.ml.calibrate import ece, evaluate_calibrated, fit_calibrated, precision_at_top
from data.synthetic import generator
from data.synthetic.frames import to_core_tables

# --- metrics ---


def test_ece_is_zero_for_perfectly_calibrated_scores() -> None:
    # In each bin the mean outcome equals the mean score exactly.
    p = np.array([0.25] * 4 + [0.75] * 4)
    y = np.array([1, 0, 0, 0, 1, 1, 1, 0])
    assert ece(y, p) == pytest.approx(0.0)


def test_ece_of_confidently_wrong_scores_is_large() -> None:
    assert ece([0, 0, 0, 0], [0.9, 0.9, 0.9, 0.9]) == pytest.approx(0.9)
    assert ece([1, 1], [1.0, 1.0]) == 0.0  # a score of exactly 1.0 lands in the last bin


@pytest.mark.parametrize(
    ("y", "p"),
    [
        ([], []),
        ([1, 0], [0.5]),
        ([2, 0], [0.5, 0.5]),
        ([1, 0], [1.2, 0.5]),
        ([1, 0], [np.nan, 0.5]),
    ],
)
def test_ece_rejects_bad_input(y: list[int], p: list[float]) -> None:
    with pytest.raises(ValueError):
        ece(y, p)


def test_precision_at_top_counts_positives_in_the_best_scored_rows() -> None:
    y = np.array([0, 1, 0, 1, 0, 0, 0, 0, 0, 0])
    score = np.array([0.1, 0.9, 0.2, 0.3, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1])
    assert precision_at_top(y, score, 0.1) == 1.0  # top 1 row is the 0.9 positive
    assert precision_at_top(y, score, 0.2) == 1.0  # top 2 rows: 0.9 and 0.3, both positive
    assert precision_at_top(y, score, 0.3) == pytest.approx(2 / 3)  # adds the 0.2 negative
    assert precision_at_top(y, score, 1.0) == pytest.approx(0.2)


def test_precision_at_top_takes_at_least_one_row_and_breaks_ties_by_input_order() -> None:
    assert precision_at_top([1, 0, 0], [0.5, 0.5, 0.5], 0.01) == 1.0
    assert precision_at_top([0, 1, 0], [0.5, 0.5, 0.5], 0.01) == 0.0


@pytest.mark.parametrize("frac", [0, -0.1, 1.5])
def test_precision_at_top_rejects_bad_fraction(frac: float) -> None:
    with pytest.raises(ValueError):
        precision_at_top([1, 0], [0.5, 0.4], frac)


def test_precision_at_top_rejects_empty_and_nan() -> None:
    with pytest.raises(ValueError):
        precision_at_top([], [])
    with pytest.raises(ValueError):
        precision_at_top([1, 0], [np.nan, 0.1])


# --- calibration ---

EARLY, LATE, TEST_START = (
    pd.Timestamp(generator.TERM_START) + pd.Timedelta(days=d) for d in range(3)
)


@pytest.fixture(scope="module")
def world() -> tuple[generator.SyntheticData, pd.DataFrame]:
    """Three presentations a day apart: early and late for training, a final one for test."""
    data = generator.generate(seed=11)
    ids = list(range(1, generator.N_STUDENTS + 1))
    kind = pd.Series([i % 3 for i in ids], index=pd.Index(ids, name="student_id"))
    cohort = pd.DataFrame(
        {
            "term_start": kind.map({0: EARLY, 1: LATE, 2: TEST_START}),
            "at_risk": [i in data.struggling_ids for i in ids],
            "split": kind.map({0: "train", 1: "train", 2: "test"}),
            "unregistered_on": pd.NaT,
        },
        index=kind.index,
    )
    return data, cohort


def _training_frame(n: int = 600, seed: int = 0) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    x = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = pd.Series(rng.random(n) < 1 / (1 + np.exp(-2 * x["a"])), name="y")
    starts = pd.Series(np.where(np.arange(n) < n // 2, EARLY, LATE), index=x.index)
    return x, y, pd.to_datetime(starts)


def test_calibrator_is_fitted_on_the_latest_presentation_only() -> None:
    x, y, starts = _training_frame()
    fitted = fit_calibrated(x, y, starts)
    assert set(fitted.validation_index) == set(starts.index[starts == LATE])
    assert set(fitted.fit_index) == set(starts.index[starts == EARLY])


def test_calibrator_never_sees_test_rows(
    world: tuple[generator.SyntheticData, pd.DataFrame], monkeypatch: pytest.MonkeyPatch
) -> None:
    data, cohort = world
    seen: list[int] = []
    original = calibrate.fit_calibrated

    def spy(features: pd.DataFrame, y: pd.Series, term_start: pd.Series, *a: object) -> object:
        seen.extend(features.index)
        fitted = original(features, y, term_start)
        seen.extend(fitted.validation_index)
        seen.extend(fitted.fit_index)
        return fitted

    monkeypatch.setattr(calibrate, "fit_calibrated", spy)
    evaluate_calibrated(to_core_tables(data), cohort, weeks=[8])
    test_ids = set(cohort.index[cohort["split"] == "test"])
    assert seen and not test_ids & set(seen)


def test_fitting_is_deterministic() -> None:
    x, y, starts = _training_frame()
    a = fit_calibrated(x, y, starts)
    b = fit_calibrated(x.copy(), y.copy(), starts)
    probe = x.head(50)
    np.testing.assert_array_equal(a.predict_proba(probe), b.predict_proba(probe))


def test_calibrated_output_is_monotone_in_the_raw_score_and_a_probability() -> None:
    x, y, starts = _training_frame()
    fitted = fit_calibrated(x, y, starts)
    grid = pd.DataFrame({"a": np.linspace(-6, 6, 200), "b": 0.0})
    raw, cal = fitted.raw_score(grid), fitted.predict_proba(grid)
    order = np.argsort(raw, kind="stable")
    assert (np.diff(cal[order]) >= 0).all()
    assert ((cal >= 0) & (cal <= 1)).all()


def test_calibrated_scores_are_well_calibrated_on_fresh_data() -> None:
    x, y, starts = _training_frame(n=3000, seed=3)
    fitted = fit_calibrated(x, y, starts)
    x_new, y_new, _ = _training_frame(n=3000, seed=4)
    assert ece(y_new, fitted.predict_proba(x_new)) <= 0.08


def test_fit_calibrated_refuses_a_single_presentation() -> None:
    x, y, starts = _training_frame()
    with pytest.raises(ValueError, match="two training presentations"):
        fit_calibrated(x, y, pd.Series(EARLY, index=x.index))


def test_fit_calibrated_refuses_a_part_without_both_classes() -> None:
    x, y, starts = _training_frame()
    y = y.copy()
    y[starts == LATE] = False
    with pytest.raises(ValueError, match="validation part needs both classes"):
        fit_calibrated(x, y, starts)


def test_fit_calibrated_refuses_misaligned_inputs() -> None:
    x, y, starts = _training_frame()
    with pytest.raises(ValueError, match="same index"):
        fit_calibrated(x, y.reset_index(drop=True).iloc[::-1], starts)


def test_evaluate_calibrated_table(world: tuple[generator.SyntheticData, pd.DataFrame]) -> None:
    data, cohort = world
    result = evaluate_calibrated(to_core_tables(data), cohort)
    assert result["week"].tolist() == list(WEEKS)
    late = result.set_index("week").loc[8]
    assert 0 <= late["ece"] <= 1
    assert late["auc_cal"] > 0.8
    assert late["top10_lift"] >= 2
    assert bool(late["lift_ok"]) is True
    assert bool(late["ece_ok"]) == (late["ece"] <= calibrate.ECE_TARGET)


def test_evaluate_calibrated_marks_weeks_without_test_positives_as_missing(
    world: tuple[generator.SyntheticData, pd.DataFrame],
) -> None:
    data, cohort = world
    flat = cohort.copy()
    flat.loc[flat["split"] == "test", "at_risk"] = False
    result = evaluate_calibrated(to_core_tables(data), flat, weeks=[8])
    assert result["ece"].isna().all()
    assert not result["ece_ok"].any()
