"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import BandBadge from "@/components/BandBadge";
import { STATE_LABEL } from "@/lib/actions";
import { ApiError, loadCaseload } from "@/lib/api";
import type { CasePage, CaseState } from "@/lib/types";

const PAGE_SIZE = 50;

/**
 * A paged list of cases, optionally of one state. The API decides which cases the signed-in
 * person may see and in what order; this only shows them (the band, never a score).
 */
export default function CaseList({
  state,
  intro,
  empty,
  noun,
}: {
  state?: CaseState;
  intro: string;
  empty: string;
  noun: [string, string]; // singular and plural, e.g. ["open case", "open cases"]
}) {
  const [page, setPage] = useState<CasePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    let current = true;
    loadCaseload({ state, limit: PAGE_SIZE, offset })
      .then((data) => current && setPage(data))
      .catch(
        (e: unknown) =>
          current && setError(e instanceof ApiError ? e.message : "failed"),
      );
    return () => {
      current = false;
    };
  }, [state, offset]);

  if (error) return <p role="alert">Could not load cases: {error}.</p>;
  if (!page) return <p className="muted">Loading cases…</p>;
  if (page.total === 0) return <p>{empty}</p>;

  return (
    <>
      <p className="muted">
        {page.total} {page.total === 1 ? noun[0] : noun[1]}. {intro}
      </p>
      <ul className="cards">
        {page.items.map((c) => (
          <li key={c.id}>
            <Link href={`/cases/${c.id}`} className="card">
              <span className="row">
                <strong>Student {c.student_id}</strong>
                <BandBadge band={c.band} />
              </span>
              <span className="row muted">
                <span>{STATE_LABEL[c.state]}</span>
                <span>
                  {c.due_on ? `Due ${c.due_on}` : "No due date"}
                  {c.overdue ? " · overdue" : ""}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <div className="row">
        <button
          type="button"
          disabled={offset === 0}
          onClick={() => setOffset(offset - PAGE_SIZE)}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={offset + PAGE_SIZE >= page.total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Next
        </button>
      </div>
    </>
  );
}
