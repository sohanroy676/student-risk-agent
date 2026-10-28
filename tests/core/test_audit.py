from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.audit import (
    GENESIS,
    AuditEntry,
    StoredEntry,
    canonical,
    check_detail,
    entry_hash,
    verify_entries,
)

T0 = datetime(2026, 3, 2, 1, 0, 0, 123456, tzinfo=UTC)


def make(seq: int = 1, **over: Any) -> AuditEntry:
    fields: dict[str, Any] = {
        "seq": seq,
        "at": T0 + timedelta(minutes=seq),
        "actor_kind": "system",
        "actor_id": None,
        "action": "case.opened",
        "subject_kind": "case",
        "subject_ref": f"case-{seq}",
        "detail": {"reason": "red", "cycle": 1},
    }
    fields.update(over)
    return AuditEntry(**fields)


def chain(n: int) -> list[StoredEntry]:
    out: list[StoredEntry] = []
    prev = GENESIS
    for seq in range(1, n + 1):
        entry = make(seq)
        out.append(StoredEntry(entry, prev, entry_hash(prev, entry)))
        prev = out[-1].hash
    return out


def test_known_answer_pins_the_hash_format() -> None:
    entry = make(1)
    assert canonical(entry) == (
        '{"action":"case.opened","actor_id":null,"actor_kind":"system",'
        '"at":"2026-03-02T01:01:00.123456+00:00","detail":{"cycle":1,"reason":"red"},'
        '"seq":1,"subject_kind":"case","subject_ref":"case-1"}'
    )
    assert entry_hash(GENESIS, entry) == (
        "4f6dfb3c7a0d311f7321b9643e4fc76796269d8fc02010d5a5c6ada7499ac5e3"
    )


def test_hash_is_deterministic_and_ignores_detail_key_order() -> None:
    a = make(detail={"a": 1, "b": 2})
    b = make(detail={"b": 2, "a": 1})
    assert entry_hash(GENESIS, a) == entry_hash(GENESIS, b)


def test_the_same_instant_in_another_timezone_hashes_the_same() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    assert entry_hash(GENESIS, make(at=T0)) == entry_hash(GENESIS, make(at=T0.astimezone(ist)))


@pytest.mark.parametrize(
    "change",
    [
        {"seq": 2},
        {"at": T0 + timedelta(microseconds=1)},
        {"actor_kind": "mentor"},
        {"actor_id": "m1"},
        {"action": "case.closed"},
        {"subject_kind": "student"},
        {"subject_ref": "case-2"},
        {"detail": {"reason": "red", "cycle": 2}},
    ],
)
def test_changing_any_field_changes_the_hash(change: dict[str, Any]) -> None:
    base = make(1, at=T0, subject_ref="case-1", detail={"reason": "red", "cycle": 1})
    assert entry_hash(GENESIS, replace(base, **change)) != entry_hash(GENESIS, base)


def test_the_previous_hash_is_part_of_the_hash() -> None:
    entry = make()
    assert entry_hash(GENESIS, entry) != entry_hash("1" * 64, entry)


def test_a_null_actor_and_the_string_null_are_different() -> None:
    assert entry_hash(GENESIS, make(actor_id=None)) != entry_hash(GENESIS, make(actor_id="null"))


@pytest.mark.parametrize(
    "bad",
    [
        {"seq": 0},
        {"seq": -1},
        {"at": datetime(2026, 3, 2)},
        {"actor_kind": " "},
        {"action": ""},
        {"subject_kind": ""},
    ],
)
def test_malformed_entries_are_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        make(**bad)


@pytest.mark.parametrize(
    "detail",
    [
        {"student_name": "A"},
        {"Phone": "1"},
        {"nested": {"email": "x"}},
        {"items": [{"roll_no": "1"}]},
        {"probability": 1},
        {"risk_band": "red"},
        {"score": 3},
        {"p": 0.5},
        {"items": [1.5]},
        {"when": datetime(2026, 1, 1)},
        {"t": (1, 2)},
        {"s": {1, 2}},
        {1: "x"},
    ],
)
def test_detail_with_banned_keys_or_unstable_types_is_refused(detail: dict[Any, Any]) -> None:
    with pytest.raises(ValueError):
        make(detail=detail)


def test_plain_facts_are_allowed_in_detail() -> None:
    check_detail({"reason": "red", "cycle": 2, "ok": True, "none": None, "ids": [1, 2], "d": {}})


def test_an_empty_log_verifies_and_its_head_is_the_genesis_hash() -> None:
    result = verify_entries([])
    assert result.ok and result.checked == 0 and result.head == GENESIS


def test_an_intact_chain_verifies_and_reports_its_head() -> None:
    entries = chain(5)
    result = verify_entries(entries)
    assert result.ok and result.checked == 5 and result.head == entries[-1].hash


def test_editing_a_row_is_found_at_that_row() -> None:
    entries = chain(5)
    entries[2] = replace(entries[2], entry=replace(entries[2].entry, action="case.dismissed"))
    result = verify_entries(entries)
    assert not result.ok and result.first_bad_seq == 3 and result.checked == 2


def test_rehashing_an_edited_row_still_breaks_the_next_one() -> None:
    entries = chain(5)
    edited = replace(entries[2].entry, action="case.dismissed")
    entries[2] = StoredEntry(edited, entries[2].prev_hash, entry_hash(entries[2].prev_hash, edited))
    result = verify_entries(entries)
    assert not result.ok and result.first_bad_seq == 4


def test_deleting_a_middle_row_is_found_as_a_gap() -> None:
    entries = chain(5)
    del entries[2]
    result = verify_entries(entries)
    assert not result.ok and result.first_bad_seq == 4 and "missing" in (result.problem or "")


def test_deleting_the_first_row_is_found() -> None:
    result = verify_entries(chain(3)[1:])
    assert not result.ok and result.first_bad_seq == 2


def test_swapping_two_rows_is_found() -> None:
    entries = chain(4)
    entries[1], entries[2] = entries[2], entries[1]
    assert not verify_entries(entries).ok


def test_replacing_a_stored_hash_or_prev_hash_is_found() -> None:
    entries = chain(4)
    forged = list(entries)
    forged[1] = replace(forged[1], hash="a" * 64)
    assert verify_entries(forged).first_bad_seq == 2
    forged = list(entries)
    forged[3] = replace(forged[3], prev_hash="b" * 64)
    assert verify_entries(forged).first_bad_seq == 4


def test_cutting_off_the_newest_rows_is_only_visible_against_a_saved_head() -> None:
    entries = chain(5)
    saved_head = verify_entries(entries).head
    shorter = verify_entries(entries[:3])
    assert shorter.ok  # the chain itself cannot tell
    assert shorter.head != saved_head  # an anchor kept elsewhere can


@given(
    n=st.integers(min_value=1, max_value=12),
    victim=st.integers(min_value=0, max_value=11),
    field=st.sampled_from(["actor_kind", "actor_id", "action", "subject_kind", "subject_ref"]),
    text=st.text(alphabet=st.characters(categories=("L", "N")), min_size=1, max_size=8),
)
def test_any_single_field_edit_is_always_found(n: int, victim: int, field: str, text: str) -> None:
    entries = chain(n)
    k = victim % n
    current = getattr(entries[k].entry, field)
    if current == text:
        return
    entries[k] = replace(entries[k], entry=replace(entries[k].entry, **{field: text}))
    result = verify_entries(entries)
    assert not result.ok and result.first_bad_seq == k + 1
