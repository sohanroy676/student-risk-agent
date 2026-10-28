from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.core.audit import (
    GENESIS,
    Anchor,
    AuditEntry,
    StoredEntry,
    entry_hash,
    verify_entries,
)


def chain(n: int) -> list[StoredEntry]:
    out: list[StoredEntry] = []
    prev = GENESIS
    for seq in range(1, n + 1):
        entry = AuditEntry(
            seq, datetime(2026, 3, 2, tzinfo=UTC) + timedelta(minutes=seq), "system", None,
            "case.opened", "case", f"case-{seq}",
        )  # fmt: skip
        out.append(StoredEntry(entry, prev, entry_hash(prev, entry)))
        prev = out[-1].hash
    return out


def test_an_anchor_round_trips_through_text() -> None:
    anchor = Anchor(7, "ab" * 32)
    assert Anchor.parse(str(anchor)) == anchor
    assert Anchor.parse(f"  {anchor}\n") == anchor


@pytest.mark.parametrize(
    "text",
    ["", "7", "7:", ":" + "a" * 64, "0:" + "a" * 64, "-1:" + "a" * 64, "x:" + "a" * 64]
    + ["7:" + "a" * 63, "7:" + "A" * 64, "7:" + "g" * 64, "7:" + "a" * 65],
)
def test_a_malformed_anchor_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="anchor"):
        Anchor.parse(text)


def test_a_matching_anchor_passes_with_and_without_later_entries() -> None:
    entries = chain(5)
    anchor = Anchor(3, entries[2].hash)
    assert verify_entries(entries, anchor).ok
    assert verify_entries(entries[:3], anchor).ok


def test_a_log_shorter_than_the_anchor_is_reported_as_cut_off() -> None:
    entries = chain(5)
    result = verify_entries(entries[:3], Anchor(5, entries[4].hash))
    assert not result.ok and result.first_bad_seq == 4 and "cut off" in (result.problem or "")


def test_an_empty_log_fails_against_any_anchor() -> None:
    assert not verify_entries([], Anchor(1, "a" * 64)).ok


def test_rewriting_every_row_consistently_still_fails_the_anchor() -> None:
    entries = chain(4)
    anchor = Anchor(4, entries[3].hash)
    forged: list[StoredEntry] = []
    prev = GENESIS
    for item in entries:
        edited = replace(item.entry, actor_id="mallory")
        forged.append(StoredEntry(edited, prev, entry_hash(prev, edited)))
        prev = forged[-1].hash
    assert verify_entries(forged).ok  # a perfect forgery passes the chain alone
    result = verify_entries(forged, anchor)
    assert not result.ok and result.first_bad_seq == 4 and "rewritten" in (result.problem or "")
