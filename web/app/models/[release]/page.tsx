"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import {
  ApiError,
  loadModelCard,
  loadRelease,
  promoteRelease,
} from "@/lib/api";
import { RECALL_GAP_LIMIT, explainCode, number3 } from "@/lib/models";
import type { ModelRelease } from "@/lib/types";
import { useSession } from "@/lib/use-session";

const REASON_LIMIT = 1000;

function describe(error: unknown): string {
  return error instanceof ApiError ? error.message : "something went wrong";
}

function Promotion({
  release,
  onPromote,
  busy,
}: {
  release: ModelRelease;
  onPromote: (reason: string, covers: string[]) => void;
  busy: boolean;
}) {
  const { subject } = useSession();
  const [covered, setCovered] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const gate = release.gate_now;

  if (release.in_production) return <p>This release is in production.</p>;
  if (gate === null) {
    return (
      <p className="muted">
        The gate cannot judge this release (its numbers are unreadable).
      </p>
    );
  }
  if (gate.hard_failures.length > 0) {
    return (
      <>
        <p role="alert">
          This release cannot be promoted, and no sign-off can change that: the
          gate cannot judge numbers it cannot see.
        </p>
        <ul>
          {gate.hard_failures.map((code) => (
            <li key={code}>{explainCode(code)}</li>
          ))}
        </ul>
      </>
    );
  }
  if (gate.passed) {
    return (
      <button type="button" disabled={busy} onClick={() => onPromote("", [])}>
        Promote to production
      </button>
    );
  }

  const allCovered = gate.blocks.every((code) => covered.includes(code));
  const ready = allCovered && reason.trim() !== "";
  const toggle = (code: string) =>
    setCovered((now) =>
      now.includes(code) ? now.filter((c) => c !== code) : [...now, code],
    );

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) onPromote(reason.trim(), covered);
      }}
    >
      <p>
        The gate blocks this release. A named person can accept each block
        below, with a reason. The sign-off is recorded in your name
        {subject ? ` (${subject})` : ""} and cannot be changed afterwards.
      </p>
      <fieldset>
        <legend>I accept these blocks</legend>
        {gate.blocks.map((code) => (
          <label key={code} className="check">
            <input
              type="checkbox"
              checked={covered.includes(code)}
              onChange={() => toggle(code)}
            />
            <span>
              <code>{code}</code> {explainCode(code)}
            </span>
          </label>
        ))}
      </fieldset>
      <label htmlFor="reason">Reason for the sign-off</label>
      <textarea
        id="reason"
        rows={4}
        maxLength={REASON_LIMIT}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <button type="submit" disabled={busy || !ready}>
        Promote with sign-off
      </button>
      {!ready && (
        <p className="muted small">
          Tick every block and give a reason to continue.
        </p>
      )}
    </form>
  );
}

function Detail({ id }: { id: number }) {
  const [release, setRelease] = useState<ModelRelease | null>(null);
  const [card, setCard] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRelease(await loadRelease(id));
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
    loadModelCard(id)
      .then((c) => setCard(c.markdown))
      .catch(() => setCard(null));
  }, [id, load]);

  if (error && !release)
    return <p role="alert">Could not load this release: {error}.</p>;
  if (!release) return <p className="muted">Loading release…</p>;

  const promote = async (reason: string, covers: string[]) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await promoteRelease(id, { reason, covers });
      await load();
      setNotice(`Release ${id} is now in production.`);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  const gaps = Object.entries(release.metrics?.recall_gaps ?? {});
  const blocks = new Set(release.gate_now?.blocks ?? []);

  return (
    <>
      <section aria-labelledby="summary">
        <h2 id="summary">
          Release {release.release}{" "}
          {release.in_production && (
            <span className="badge badge-ok">In production</span>
          )}
        </h2>
        <dl className="facts">
          <dt>Registered</dt>
          <dd>{release.created.slice(0, 10)}</dd>
          <dt>Weeks</dt>
          <dd>{release.weeks.join(", ")}</dd>
          <dt>Week-4 AUC</dt>
          <dd>{number3(release.metrics?.auc_week4)}</dd>
          <dt>Calibration error</dt>
          <dd>{number3(release.metrics?.ece)}</dd>
          {release.sign_off && (
            <>
              <dt>Signed off by</dt>
              <dd>
                {release.sign_off.name}: {release.sign_off.reason}
              </dd>
            </>
          )}
        </dl>
      </section>

      <section aria-labelledby="fairness">
        <h2 id="fairness">Fairness: recall gap between groups</h2>
        {gaps.length === 0 ? (
          <p className="muted">No fairness numbers were recorded.</p>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Attribute</th>
                  <th scope="col">Largest gap</th>
                  <th scope="col">
                    Against the {RECALL_GAP_LIMIT.toFixed(2)} limit
                  </th>
                </tr>
              </thead>
              <tbody>
                {gaps.map(([attribute, gap]) => (
                  <tr key={attribute}>
                    <th scope="row">{attribute}</th>
                    <td>{number3(gap)}</td>
                    <td>
                      {gap === null
                        ? "Not assessed"
                        : blocks.has(`gap_high:${attribute}`) ||
                            gap > RECALL_GAP_LIMIT
                          ? "Above the limit"
                          : "Within the limit"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="gate">
        <h2 id="gate">Promotion gate</h2>
        {error && <p role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {release.gate_now && release.gate_now.blocks.length > 0 && (
          <ul>
            {release.gate_now.blocks.map((code) => (
              <li key={code}>
                <code>{code}</code> {explainCode(code)}
              </li>
            ))}
          </ul>
        )}
        <Promotion release={release} onPromote={promote} busy={busy} />
      </section>

      <section aria-labelledby="card">
        <h2 id="card">Model card</h2>
        {card === null ? (
          <p className="muted">The model card could not be loaded.</p>
        ) : (
          <details>
            <summary>Show the full card</summary>
            <pre className="card-text">{card}</pre>
          </details>
        )}
      </section>
    </>
  );
}

export default function ReleasePage() {
  const params = useParams<{ release: string }>();
  const id = Number(params.release);
  return (
    <AppShell roles={["admin"]} title="Model release">
      {Number.isInteger(id) && id > 0 ? (
        <Detail id={id} />
      ) : (
        <p role="alert">Unknown release.</p>
      )}
    </AppShell>
  );
}
