"""Hash-chained audit log: the pure part (entries, hashing, chain verification).

Each entry's hash covers the previous entry's hash and the entry itself, so changing, removing
or reordering a row breaks every hash after it. Entries are numbered 1, 2, 3, ... with no gaps
(the writer takes the number under a lock, not from a sequence, which skips values on rollback),
so a deleted row shows up as a gap.

The chain cannot show that the newest rows were cut off; keep the head hash somewhere else
(`anchor`) to catch that. `detail` holds facts about the action, never student names, contact
details, roll numbers, or risk scores and bands, and no floats (JSON numbers must round-trip
through Postgres jsonb byte for byte, and a probability does not belong in the log anyway).
"""

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

GENESIS = "0" * 64
HEX64 = re.compile(r"[0-9a-f]{64}")

# Keys that must never appear in `detail` (matched as substrings, case-insensitive).
BANNED_DETAIL_KEYS = (
    "name",
    "phone",
    "mobile",
    "email",
    "roll",
    "address",
    "probability",
    "score",
    "band",
    "risk",
)


def check_detail(value: Any, path: str = "detail") -> None:
    """Raise `ValueError` if `value` holds a banned key or any type that would not round-trip."""
    if isinstance(value, dict):
        for key, inner in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: keys must be strings")
            lowered = key.lower()
            if any(banned in lowered for banned in BANNED_DETAIL_KEYS):
                raise ValueError(f"{path}.{key}: this key is not allowed in an audit entry")
            check_detail(inner, f"{path}.{key}")
    elif isinstance(value, list):
        for i, inner in enumerate(value):
            check_detail(inner, f"{path}[{i}]")
    elif isinstance(value, float) or not (value is None or isinstance(value, str | int | bool)):
        raise ValueError(f"{path}: {type(value).__name__} is not allowed in an audit entry")


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    at: datetime
    actor_kind: str
    actor_id: str | None
    action: str
    subject_kind: str
    subject_ref: str | None
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.seq < 1:
            raise ValueError("seq starts at 1")
        if self.at.tzinfo is None:
            raise ValueError("at must be timezone-aware")
        for name in ("actor_kind", "action", "subject_kind"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        check_detail(self.detail)


def canonical(entry: AuditEntry) -> str:
    """One fixed text form per entry: sorted keys, no spaces, UTC time to the microsecond."""
    return json.dumps(
        {
            "seq": entry.seq,
            "at": entry.at.astimezone(UTC).isoformat(timespec="microseconds"),
            "actor_kind": entry.actor_kind,
            "actor_id": entry.actor_id,
            "action": entry.action,
            "subject_kind": entry.subject_kind,
            "subject_ref": entry.subject_ref,
            "detail": entry.detail,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def entry_hash(prev_hash: str, entry: AuditEntry) -> str:
    return hashlib.sha256(f"{prev_hash}\n{canonical(entry)}".encode("ascii")).hexdigest()


@dataclass(frozen=True)
class StoredEntry:
    entry: AuditEntry
    prev_hash: str
    hash: str


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    head: str
    first_bad_seq: int | None = None
    problem: str | None = None


@dataclass(frozen=True)
class Anchor:
    """The head of the log at some moment, kept somewhere else (`seq:hash`)."""

    seq: int
    hash: str

    def __str__(self) -> str:
        return f"{self.seq}:{self.hash}"

    @classmethod
    def parse(cls, text: str) -> "Anchor":
        seq, _, digest = text.strip().partition(":")
        if not (seq.isdecimal() and int(seq) >= 1 and HEX64.fullmatch(digest)):
            raise ValueError("an anchor looks like <seq>:<64 lowercase hex characters>")
        return cls(int(seq), digest)


def verify_entries(stored: Iterable[StoredEntry], anchor: Anchor | None = None) -> VerifyResult:
    """Walk entries in seq order; stop at the first one that does not fit the chain.

    With an `anchor`, the entry it names must still have the saved hash (catching a rewrite
    that re-hashes every row) and the log must not be shorter than it (catching cut-off rows).
    """
    head = GENESIS
    checked = 0
    for item in stored:
        problem = _problem(item, checked + 1, head)
        at_anchor = anchor is not None and item.entry.seq == anchor.seq
        if problem is None and at_anchor and anchor is not None and item.hash != anchor.hash:
            problem = "entry does not match the saved anchor (history was rewritten)"
        if problem is not None:
            return VerifyResult(False, checked, head, item.entry.seq, problem)
        head = item.hash
        checked += 1
    if anchor is not None and checked < anchor.seq:
        problem = f"log has {checked} entries but the anchor is entry {anchor.seq} (cut off)"
        return VerifyResult(False, checked, head, checked + 1, problem)
    return VerifyResult(True, checked, head)


def _problem(item: StoredEntry, expected_seq: int, head: str) -> str | None:
    if item.entry.seq != expected_seq:
        return f"expected entry {expected_seq}, found {item.entry.seq} (a row is missing or moved)"
    if item.prev_hash != head:
        return "prev_hash does not match the entry before it"
    if item.hash != entry_hash(item.prev_hash, item.entry):
        return "hash does not match the entry's contents"
    return None
