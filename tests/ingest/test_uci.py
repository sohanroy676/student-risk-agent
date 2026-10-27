from pathlib import Path

import pytest

from app.ingest.uci import load_uci

HEADER = (
    "Marital status;Gender;Age at enrollment;Nationality;Debtor;"
    "Curricular units 1st sem (grades);Target"
)


def _write(path: Path, rows: list[str], header: str = HEADER) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_labels_and_column_normalisation(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "data.csv",
        ["1;1;20;1;0;12.5;Dropout", "1;0;22;1;1;14.0;Graduate", "2;1;19;6;0;0;Enrolled"],
    )
    data = load_uci(path)
    assert data.labels.tolist() == [True, False, False]
    assert "curricular_units_1st_sem_grades" in data.features.columns
    assert "debtor" in data.features.columns


def test_protected_columns_are_split_out(tmp_path: Path) -> None:
    data = load_uci(_write(tmp_path / "data.csv", ["1;1;20;1;0;12.5;Dropout"]))
    assert set(data.attributes.columns) == {
        "marital_status",
        "gender",
        "age_at_enrollment",
        "nationality",
    }
    assert not set(data.attributes.columns) & set(data.features.columns)
    assert "target" not in data.features.columns


def test_comma_separated_reexport_is_accepted(tmp_path: Path) -> None:
    path = _write(tmp_path / "data.csv", ["1,1,20,1,0,12.5,Dropout"], HEADER.replace(";", ","))
    assert load_uci(path).labels.tolist() == [True]


def test_target_whitespace_and_case_of_other_labels(tmp_path: Path) -> None:
    path = _write(tmp_path / "data.csv", ["1;1;20;1;0;1;Dropout ", "1;1;20;1;0;1;dropout"])
    # Only the exact (trimmed) value counts: a differently-cased label is not silently mapped.
    assert load_uci(path).labels.tolist() == [True, False]


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing"):
        load_uci(tmp_path / "nope.csv")


def test_missing_target_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "data.csv", ["1;1;20"], "Marital status;Gender;Age at enrollment")
    with pytest.raises(ValueError, match="Target"):
        load_uci(path)


def test_colliding_normalised_columns_raise(tmp_path: Path) -> None:
    path = _write(tmp_path / "data.csv", ["1;2;Dropout"], "Debtor;debtor;Target")
    with pytest.raises(ValueError, match="collide"):
        load_uci(path)


def test_real_file_quirks_bom_misspelling_and_tab_in_header(tmp_path: Path) -> None:
    header = '﻿Marital status;Nacionality;"Daytime/evening attendance\t";Gender;Target'
    path = tmp_path / "data.csv"
    path.write_text(f"{header}\n1;1;1;1;Dropout\n", encoding="utf-8")
    data = load_uci(path)
    assert "nacionality" not in data.features.columns
    assert "nacionality" in data.attributes.columns
    assert "marital_status" in data.attributes.columns
    assert "daytime_evening_attendance" in data.features.columns
