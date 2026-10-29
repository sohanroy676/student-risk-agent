"use client";

import { useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import { ApiError, loadAudit, verifyAudit } from "@/lib/api";
import type { AuditCheck, AuditPage } from "@/lib/types";

const PAGE_SIZE = 50;

function describe(error: unknown): string {
  return error instanceof ApiError ? error.message : "something went wrong";
}

function ChainCheck() {
  const [anchor, setAnchor] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AuditCheck | null>(null);
  const [error, setError] = useState<string | null>(null);

  const check = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await verifyAudit(anchor.trim() || undefined));
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={check} aria-labelledby="chain">
      <h2 id="chain">Check the log has not been changed</h2>
      <p className="muted">
        Recomputes the chain of entries. To also catch recent entries cut off
        the end, paste an anchor you saved earlier and kept outside this
        database.
      </p>
      <label htmlFor="anchor">Saved anchor (optional)</label>
      <input
        id="anchor"
        type="text"
        autoComplete="off"
        maxLength={100}
        placeholder="SEQ:HASH"
        value={anchor}
        onChange={(e) => setAnchor(e.target.value)}
      />
      {error && <p role="alert">{error}</p>}
      {result && result.ok && (
        <p role="status">
          Intact: {result.checked} {result.checked === 1 ? "entry" : "entries"}{" "}
          checked.
          {result.anchor && (
            <>
              {" "}
              Current anchor to keep: <code>{result.anchor}</code>
            </>
          )}
        </p>
      )}
      {result && !result.ok && (
        <p role="alert">
          The log does not check out
          {result.first_bad_seq !== null
            ? ` (first problem at entry ${result.first_bad_seq})`
            : ""}
          : {result.problem ?? "unknown problem"}.
        </p>
      )}
      <button type="submit" disabled={busy}>
        Check now
      </button>
    </form>
  );
}

function Entries() {
  const [page, setPage] = useState<AuditPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [applied, setApplied] = useState("");

  useEffect(() => {
    let current = true;
    loadAudit({ action: applied, limit: PAGE_SIZE, offset })
      .then((data) => {
        if (!current) return;
        setError(null);
        setPage(data);
      })
      .catch((e: unknown) => current && setError(describe(e)));
    return () => {
      current = false;
    };
  }, [applied, offset]);

  const apply = (event: React.FormEvent) => {
    event.preventDefault();
    setOffset(0);
    setApplied(action.trim());
  };

  return (
    <section aria-labelledby="entries">
      <h2 id="entries">Entries</h2>
      <form onSubmit={apply}>
        <label htmlFor="action">Show only this action (exact)</label>
        <input
          id="action"
          type="text"
          autoComplete="off"
          maxLength={100}
          placeholder="e.g. nightly.run"
          value={action}
          onChange={(e) => setAction(e.target.value)}
        />
        <button type="submit">Filter</button>
      </form>
      {error && <p role="alert">Could not load the log: {error}.</p>}
      {!error && !page && <p className="muted">Loading the log…</p>}
      {!error && page && page.total === 0 && <p>No entries.</p>}
      {!error && page && page.total > 0 && (
        <>
          <p className="muted">
            {page.total} {page.total === 1 ? "entry" : "entries"}, newest first.
            The details of each entry are not shown here.
          </p>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">No.</th>
                  <th scope="col">When</th>
                  <th scope="col">Who</th>
                  <th scope="col">Action</th>
                  <th scope="col">Record</th>
                  <th scope="col">Hash</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((e) => (
                  <tr key={e.seq}>
                    <th scope="row">{e.seq}</th>
                    <td>{new Date(e.at).toLocaleString()}</td>
                    <td>
                      {e.actor_kind}
                      {e.actor_id ? ` · ${e.actor_id}` : ""}
                    </td>
                    <td>{e.action}</td>
                    <td>
                      {e.subject_kind}
                      {e.subject_ref ? ` · ${e.subject_ref}` : ""}
                    </td>
                    <td>
                      <code>{e.hash_prefix}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
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
      )}
    </section>
  );
}

export default function AuditScreen() {
  return (
    <AppShell roles={["admin"]} title="Audit log">
      <ChainCheck />
      <Entries />
    </AppShell>
  );
}
