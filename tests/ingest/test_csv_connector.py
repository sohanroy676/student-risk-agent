from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from app.ingest.csv_connector import check_csv_dir, main, read_csv_dir
from data.synthetic import generator
from data.synthetic.frames import to_frames

# One day after the synthetic term ends, so nothing looks stale or future-dated.
RUN = date(2026, 4, 20)


def write(directory: Path, name: str, text: str) -> None:
    (directory / f"{name}.csv").write_text(text, encoding="utf-8")


def test_missing_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_csv_dir(tmp_path / "nope")


def test_reader_keeps_text_and_row_numbers(tmp_path: Path) -> None:
    write(tmp_path, "courses", "id,code,title\n1,CS101,\n2,NA,null\n")
    write(tmp_path, "unrelated", "a,b\n1,2\n")
    frames = read_csv_dir(tmp_path)
    assert set(frames) == {"courses"}
    assert frames["courses"]["title"].tolist() == ["", "null"]
    assert frames["courses"]["code"].tolist() == ["CS101", "NA"]
    assert frames["courses"]["_row"].tolist() == [2, 3]


def test_reader_handles_bom_and_messy_headers(tmp_path: Path) -> None:
    (tmp_path / "courses.csv").write_bytes("﻿ Id , CODE ,Title\n1,A,B\n".encode())
    assert list(read_csv_dir(tmp_path)["courses"].columns)[:3] == ["id", "code", "title"]


def test_malformed_csv_is_a_clear_error(tmp_path: Path) -> None:
    (tmp_path / "courses.csv").write_bytes(b"id,code\n\xff\xfe\x00bad\n")
    with pytest.raises(ValueError, match="courses.csv cannot be read"):
        read_csv_dir(tmp_path)


def test_missing_required_column_is_a_clear_error(tmp_path: Path) -> None:
    write(tmp_path, "students", "id\n1\n")
    with pytest.raises(ValueError, match="students is missing columns"):
        check_csv_dir(tmp_path, RUN)


def test_synthetic_export_loads_clean_and_matches_the_generator(tmp_path: Path) -> None:
    data = generator.generate(seed=3)
    generator.write_csv(data, tmp_path)
    result, report = check_csv_dir(tmp_path, RUN)
    assert result.issues == []
    assert report.status == "ok"
    expected = to_frames(data)
    for name, frame in result.tables.items():
        # The generator emits some identical LMS events; the cleaner drops exact copies.
        want = expected[name].drop_duplicates(keep="last").reset_index(drop=True)
        assert len(frame) == len(want), name
        converted, got = want.copy(), frame.copy()
        for column in converted.columns:
            if frame[column].dtype.kind == "M":
                # Pandas picks different time units for parsed text and Python dates.
                converted[column] = pd.to_datetime(converted[column]).astype("datetime64[ns]")
                got[column] = got[column].astype("datetime64[ns]")
        assert_frame_equal(got, converted, check_dtype=False, obj=name)


def test_cli_dry_run_prints_report_and_sets_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    generator.write_csv(generator.generate(seed=3), tmp_path)
    assert main([str(tmp_path), "--dry-run", "--run-date", RUN.isoformat()]) == 0
    assert "Data quality 2026-04-20: OK" in capsys.readouterr().out
    (tmp_path / "attendance.csv").write_text("student_id,course_id,class_date,present\n")
    assert main([str(tmp_path), "--dry-run", "--run-date", RUN.isoformat()]) == 1


def test_cli_without_database_url_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main([str(tmp_path)])
