"""CI runs database tests in shards by folder; a folder missing from every shard would be skipped
silently (the no-database job deselects those tests). This fails first."""

import re
from pathlib import Path

TESTS = Path(__file__).parent
WORKFLOW = TESTS.parent / ".github" / "workflows" / "ci.yml"


def _folders_with_database_tests() -> set[str]:
    found = set()
    for path in TESTS.rglob("test_*.py"):
        if "TEST_DATABASE_URL" in path.read_text(encoding="utf-8") and path != Path(__file__):
            found.add(f"tests/{path.parent.relative_to(TESTS).as_posix()}".rstrip("/."))
    return found


def _shard_folders() -> set[str]:
    lines = re.findall(r"^\s+paths:\s*(.+)$", WORKFLOW.read_text(encoding="utf-8"), re.MULTILINE)
    return {folder for line in lines for folder in line.split()}


def test_there_are_database_tests_and_shards_to_compare() -> None:
    assert _folders_with_database_tests() >= {"tests/db", "tests/cases", "tests/api"}
    assert _shard_folders() >= {"tests/db", "tests/jobs"}


def test_every_folder_with_a_database_test_is_in_a_ci_shard() -> None:
    missing = _folders_with_database_tests() - _shard_folders()
    assert not missing, f"add these folders to a database shard in ci.yml: {sorted(missing)}"


def test_the_scale_test_has_its_own_job_and_the_others_exclude_it() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "marker: slow" in text
    assert text.count("marker: postgres and not slow") >= 3


def test_the_secret_scan_still_reads_the_full_history() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "gitleaks/gitleaks-action" in text and "fetch-depth: 0" in text
