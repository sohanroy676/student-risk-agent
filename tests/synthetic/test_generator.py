from datetime import date, datetime
from pathlib import Path

import pytest

from data.synthetic import generator as g


@pytest.fixture(scope="module")
def data() -> g.SyntheticData:
    return g.generate(seed=42)


def _rows(data: g.SyntheticData, name: str) -> list[tuple]:  # type: ignore[type-arg]
    return data.tables[name].rows


def _col(data: g.SyntheticData, name: str, col: str) -> list:  # type: ignore[type-arg]
    i = data.tables[name].columns.index(col)
    return [r[i] for r in data.tables[name].rows]


def test_same_seed_is_identical(data: g.SyntheticData) -> None:
    again = g.generate(seed=42)
    assert again.struggling_ids == data.struggling_ids
    for name, table in data.tables.items():
        assert again.tables[name].rows == table.rows, name


def test_different_seed_differs(data: g.SyntheticData) -> None:
    other = g.generate(seed=43)
    assert other.struggling_ids != data.struggling_ids
    assert other.tables["attendance"].rows != data.tables["attendance"].rows


def test_csv_output_is_byte_identical(tmp_path: Path) -> None:
    g.write_csv(g.generate(seed=7), tmp_path / "a")
    g.write_csv(g.generate(seed=7), tmp_path / "b")
    for f in (tmp_path / "a").iterdir():
        assert f.read_bytes() == (tmp_path / "b" / f.name).read_bytes(), f.name


def test_row_counts(data: g.SyntheticData) -> None:
    counts = {k: len(t.rows) for k, t in data.tables.items()}
    assert counts["sections"] == 6
    assert counts["students"] == 400
    assert counts["student_attributes"] == 400
    assert counts["courses"] == 5
    assert counts["enrollments"] == 400 * 5
    assert counts["attendance"] == 400 * 5 * 15 * 3 == 90_000
    assert counts["assessments"] == 5 * 4
    assert counts["marks"] == 400 * 20
    assert counts["fees"] == 800
    assert counts["lms_events"] > 40_000
    assert len(data.struggling_ids) == 40


def test_sections_are_balanced(data: g.SyntheticData) -> None:
    sizes: dict[int, int] = {}
    for s in _col(data, "students", "section_id"):
        sizes[s] = sizes.get(s, 0) + 1
    assert set(sizes) == set(range(1, 7))
    assert max(sizes.values()) - min(sizes.values()) <= 1


def test_no_duplicate_keys(data: g.SyntheticData) -> None:
    for name, cols in {
        "attendance": ("student_id", "course_id", "class_date"),
        "marks": ("assessment_id", "student_id"),
        "students": ("id",),
        "fees": ("id",),
    }.items():
        idx = [data.tables[name].columns.index(c) for c in cols]
        keys = [tuple(r[i] for i in idx) for r in data.tables[name].rows]
        assert len(keys) == len(set(keys)), name


def test_all_dates_inside_term(data: g.SyntheticData) -> None:
    for d in _col(data, "attendance", "class_date"):
        assert g.TERM_START <= d <= g.TERM_END
        assert d.weekday() < 5
    for ts in _col(data, "lms_events", "occurred_at"):
        assert isinstance(ts, datetime)
        assert g.TERM_START <= ts.date() <= g.TERM_END
    for d in _col(data, "marks", "submitted_on"):
        assert d is None or g.TERM_START <= d <= g.TERM_END
    for d in _col(data, "fees", "paid_on"):
        assert d is None or g.TERM_START <= d <= g.TERM_END


def test_marks_are_valid_and_missing_together(data: g.SyntheticData) -> None:
    for _, _, score, on in _rows(data, "marks"):
        assert (score is None) == (on is None)
        if score is not None:
            assert 0 <= score <= 100


def test_fees_are_positive_and_paid_within_term(data: g.SyntheticData) -> None:
    for _, _, due, amount, paid in _rows(data, "fees"):
        assert isinstance(due, date)
        assert amount > 0
        assert paid is None or paid >= g.TERM_START


def _mean_by_group(
    data: g.SyntheticData, rows: list[tuple], sid_i: int, val_i: int
) -> tuple[float, float]:  # type: ignore[type-arg]
    inn: list[float] = []
    out: list[float] = []
    for r in rows:
        (inn if r[sid_i] in data.struggling_ids else out).append(float(r[val_i]))
    return sum(inn) / len(inn), sum(out) / len(out)


def test_planted_students_attend_less(data: g.SyntheticData) -> None:
    s, n = _mean_by_group(data, _rows(data, "attendance"), 0, 3)
    assert s < 0.6 < 0.8 < n


def test_planted_students_submit_less_and_score_lower(data: g.SyntheticData) -> None:
    rows = _rows(data, "marks")
    s, n = _mean_by_group(data, [(r[1], r[2] is not None) for r in rows], 0, 1)
    assert s < 0.7 and n > 0.9
    scored = [(r[1], r[2]) for r in rows if r[2] is not None]
    s, n = _mean_by_group(data, scored, 0, 1)
    assert s < 50 < 65 < n


def test_planted_students_are_less_active_on_lms(data: g.SyntheticData) -> None:
    per: dict[int, int] = {}
    for sid in _col(data, "lms_events", "student_id"):
        per[sid] = per.get(sid, 0) + 1
    inn = [per.get(i, 0) for i in data.struggling_ids]
    out = [per.get(i, 0) for i in range(1, 401) if i not in data.struggling_ids]
    assert sum(inn) / len(inn) < 0.5 * sum(out) / len(out)


def test_planted_students_pay_fees_late(data: g.SyntheticData) -> None:
    rows = _rows(data, "fees")
    late = [(r[1], r[4] is None or r[4] > r[2]) for r in rows]
    s, n = _mean_by_group(data, late, 0, 1)
    assert s > 0.4 > 0.15 > n


def test_protected_attributes_only_in_attribute_table(data: g.SyntheticData) -> None:
    for name, table in data.tables.items():
        if name != "student_attributes":
            assert not {"gender", "category"} & set(table.columns), name


@pytest.mark.parametrize("n", [1, 50, 1000])
def test_n_students_sets_the_cohort_size_and_keeps_every_table_consistent(n: int) -> None:
    data = g.generate(seed=5, n_students=n)
    ids = {row[0] for row in data.tables["students"].rows}
    assert ids == set(range(1, n + 1))
    assert len(data.tables["enrollments"].rows) == n * g.N_COURSES
    assert len(data.tables["marks"].rows) == n * g.N_COURSES * len(g.ASSESSMENT_WEEKS)
    assert len(data.tables["fees"].rows) == n * g.N_FEE_INSTALMENTS
    assert len(data.tables["student_attributes"].rows) == n
    assert data.struggling_ids <= ids
    assert len(data.struggling_ids) == round(n * g.STRUGGLING_SHARE)
    for name in ("attendance", "marks", "fees", "lms_events"):
        assert set(_col(data, name, "student_id")) <= ids


def test_the_default_cohort_is_unchanged_by_the_parameter(data: g.SyntheticData) -> None:
    again = g.generate(seed=42, n_students=g.N_STUDENTS)
    assert again.tables["marks"].rows == data.tables["marks"].rows
    assert again.struggling_ids == data.struggling_ids


@pytest.mark.parametrize("n", [0, -3])
def test_a_cohort_without_students_is_refused(n: int) -> None:
    with pytest.raises(ValueError, match="n_students"):
        g.generate(n_students=n)
