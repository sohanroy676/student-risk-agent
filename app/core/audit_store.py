"""Postgres side of the audit log: append, verify, anchor.

    python -m app.core.audit_store verify [--anchor SEQ:HASH]   # exit 1 if the chain is broken
    python -m app.core.audit_store anchor                       # print SEQ:HASH to keep elsewhere

`append` runs inside the caller's transaction, so an audit row is committed or rolled back
together with the change it describes. A transaction-level advisory lock serialises writers
(the next number and previous hash are read under it), and it is held until that transaction
ends, so keep transactions that write audit entries short. Writers must use READ COMMITTED
(the default) so that, after waiting for the lock, they see the newest row.
"""

import argparse
import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Row, create_engine, text

from app.core.audit import (
    GENESIS,
    Anchor,
    AuditEntry,
    StoredEntry,
    VerifyResult,
    entry_hash,
    verify_entries,
)
from app.core.settings import get_settings

LOCK_KEY = 7_300_001
BATCH = 5000


def append(
    conn: Connection,
    *,
    actor_kind: str,
    actor_id: str | None,
    action: str,
    subject_kind: str,
    subject_ref: str | None,
    detail: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> StoredEntry:
    """Add one entry to the chain. Raises `ValueError` for a malformed entry or banned detail."""
    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
    last = conn.execute(
        text("SELECT seq, hash FROM gov.audit_log ORDER BY seq DESC LIMIT 1")
    ).one_or_none()
    seq, prev = (1, GENESIS) if last is None else (int(last.seq) + 1, str(last.hash))
    entry = AuditEntry(
        seq=seq,
        at=at or datetime.now(UTC),
        actor_kind=actor_kind,
        actor_id=actor_id,
        action=action,
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        detail=detail or {},
    )
    digest = entry_hash(prev, entry)
    conn.execute(
        text(
            "INSERT INTO gov.audit_log (seq, at, actor_kind, actor_id, action, subject_kind, "
            "subject_ref, detail, prev_hash, hash) VALUES (:seq, :at, :actor_kind, :actor_id, "
            ":action, :subject_kind, :subject_ref, CAST(:detail AS jsonb), :prev, :hash)"
        ),
        {
            "seq": seq,
            "at": entry.at,
            "actor_kind": actor_kind,
            "actor_id": actor_id,
            "action": action,
            "subject_kind": subject_kind,
            "subject_ref": subject_ref,
            "detail": json.dumps(entry.detail),
            "prev": prev,
            "hash": digest,
        },
    )
    return StoredEntry(entry, prev, digest)


def _stored(row: Row[Any]) -> StoredEntry:
    entry = AuditEntry(
        seq=int(row.seq),
        at=row.at,
        actor_kind=row.actor_kind,
        actor_id=row.actor_id,
        action=row.action,
        subject_kind=row.subject_kind,
        subject_ref=row.subject_ref,
        detail=row.detail,
    )
    return StoredEntry(entry, row.prev_hash, row.hash)


def verify(conn: Connection, anchor: Anchor | None = None) -> VerifyResult:
    """Recompute the whole chain from the stored rows, streaming them in batches."""
    result = conn.execute(
        text(
            "SELECT seq, at, actor_kind, actor_id, action, subject_kind, subject_ref, detail, "
            "prev_hash, hash FROM gov.audit_log ORDER BY seq"
        ),
        execution_options={"yield_per": BATCH},
    )
    try:
        rows: Iterator[StoredEntry] = (_stored(row) for row in result)
        return verify_entries(rows, anchor)
    finally:
        result.close()


def current_anchor(conn: Connection) -> Anchor | None:
    """Newest entry's `seq:hash`, or None for an empty log. Store it outside the database."""
    last = conn.execute(
        text("SELECT seq, hash FROM gov.audit_log ORDER BY seq DESC LIMIT 1")
    ).one_or_none()
    return None if last is None else Anchor(int(last.seq), str(last.hash))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify", help="recompute the chain; exit 1 if it is broken")
    check.add_argument("--anchor", type=Anchor.parse, default=None)
    sub.add_parser("anchor", help="print the newest entry as SEQ:HASH")
    args = parser.parse_args(argv)
    url = get_settings().database_url
    if not url:
        parser.error("DATABASE_URL is not set")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            if args.command == "anchor":
                found = current_anchor(conn)
                print(found if found else "the audit log is empty")
                return 0 if found else 1
            result = verify(conn, args.anchor)
    finally:
        engine.dispose()
    if result.ok:
        print(f"audit log intact: {result.checked} entries, head {result.head}")
        return 0
    print(f"AUDIT LOG BROKEN at entry {result.first_bad_seq}: {result.problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
