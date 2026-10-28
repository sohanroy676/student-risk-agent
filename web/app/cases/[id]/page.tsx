"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import BandBadge from "@/components/BandBadge";
import {
  ACTION_LABEL,
  STATE_LABEL,
  actionsFor,
  canEditDraft,
} from "@/lib/actions";
import { ApiError, actOnCase, loadCase, saveDraft } from "@/lib/api";
import type { CaseAction, CaseDetail } from "@/lib/types";
import { useSession } from "@/lib/use-session";

const DRAFT_LIMIT = 1000;

function describe(error: unknown): string {
  return error instanceof ApiError ? error.message : "something went wrong";
}

function Detail({ id }: { id: number }) {
  const { role } = useSession();
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await loadCase(id);
      setDetail(data);
      setText(data.draft?.message ?? "");
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !detail)
    return <p role="alert">Could not load this case: {error}.</p>;
  if (!detail || role === null) return <p className="muted">Loading case…</p>;

  const dirty = text.trim() !== (detail.draft?.message ?? "");
  const editable = canEditDraft(detail.state, role);

  const run = async (work: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await work();
      await load();
      setNotice(done);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section aria-labelledby="summary">
        <h2 id="summary">
          Student {detail.student_id} <BandBadge band={detail.band} />
        </h2>
        <dl className="facts">
          <dt>Status</dt>
          <dd>{STATE_LABEL[detail.state]}</dd>
          <dt>Cycle</dt>
          <dd>{detail.cycle}</dd>
          <dt>Opened</dt>
          <dd>{detail.opened_on}</dd>
          <dt>Due</dt>
          <dd>
            {detail.due_on ?? "none"}
            {detail.overdue ? " (overdue)" : ""}
          </dd>
          {detail.approved_by && (
            <>
              <dt>Approved</dt>
              <dd>
                {detail.approved_on} by {detail.approved_by}
              </dd>
            </>
          )}
        </dl>
      </section>

      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}

      {detail.reasons.length > 0 && (
        <section aria-labelledby="reasons">
          <h2 id="reasons">What the data shows</h2>
          <ol>
            {detail.reasons.map((r) => (
              <li key={r.fact_id}>
                {r.text} <span className="muted small">({r.fact_id})</span>
              </li>
            ))}
          </ol>
          <p className="muted small">
            These describe values only. They do not say which direction is a
            concern.
          </p>
        </section>
      )}

      <section aria-labelledby="draft">
        <h2 id="draft">Message to the student</h2>
        {detail.draft ? (
          <>
            <p className="muted small">
              Version {detail.draft.version}, {detail.draft.source} draft by{" "}
              {detail.draft.author}.
              {editable ? " Nothing is sent until you approve it." : ""}
            </p>
            {editable ? (
              <>
                <label htmlFor="draft-text">Draft message</label>
                <textarea
                  id="draft-text"
                  rows={6}
                  maxLength={DRAFT_LIMIT}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <p className="muted small">
                  {text.length}/{DRAFT_LIMIT}. Do not mention scores, bands or
                  risk.
                </p>
                <button
                  type="button"
                  disabled={busy || !dirty || text.trim() === ""}
                  onClick={() => run(() => saveDraft(id, text), "Draft saved.")}
                >
                  Save changes
                </button>
              </>
            ) : (
              <blockquote>{detail.draft.message}</blockquote>
            )}
          </>
        ) : (
          <p className="muted">
            {detail.state === "new"
              ? "A draft will be prepared tonight."
              : "No draft."}
          </p>
        )}
      </section>

      <section aria-labelledby="actions">
        <h2 id="actions">Actions</h2>
        {actionsFor(detail.state, role).length === 0 ? (
          <p className="muted">
            {role === "admin"
              ? "Administrators can read cases but not act on them."
              : "No actions are available."}
          </p>
        ) : (
          <div className="row wrap">
            {actionsFor(detail.state, role).map((action: CaseAction) => (
              <button
                key={action}
                type="button"
                disabled={busy || (action === "approve" && dirty)}
                onClick={() =>
                  run(
                    () => actOnCase(id, action),
                    `${ACTION_LABEL[action]}: done.`,
                  )
                }
              >
                {ACTION_LABEL[action]}
              </button>
            ))}
          </div>
        )}
        {dirty && editable && (
          <p className="muted small">
            Save your changes before approving, or they will not be sent.
          </p>
        )}
      </section>

      <section aria-labelledby="timeline">
        <h2 id="timeline">Timeline</h2>
        <ul className="timeline">
          {detail.timeline.map((e, i) => (
            <li key={i}>
              <span className="muted">{e.on_date}</span>{" "}
              {e.kind.replace(/_/g, " ")}
              <span className="muted small"> · {e.actor_kind}</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

export default function CasePage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  return (
    <AppShell roles={["mentor", "staff", "admin"]} title="Case">
      {Number.isInteger(id) && id > 0 ? (
        <Detail id={id} />
      ) : (
        <p role="alert">Unknown case.</p>
      )}
    </AppShell>
  );
}
