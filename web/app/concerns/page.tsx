"use client";

import { useCallback, useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import {
  ApiError,
  acknowledgeConcern,
  loadConcerns,
  raiseConcern,
} from "@/lib/api";
import { CATEGORIES, NOTE_LIMIT, categoryLabel } from "@/lib/concerns";
import type { Concern, ConcernCategory, ConcernPage, Role } from "@/lib/types";
import { useSession } from "@/lib/use-session";

const PAGE_SIZE = 50;

function describe(error: unknown): string {
  return error instanceof ApiError ? error.message : "something went wrong";
}

function RaiseForm({ onRaised }: { onRaised: () => void }) {
  const [studentId, setStudentId] = useState("");
  const [category, setCategory] = useState<ConcernCategory>("attendance");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const id = Number(studentId);
  const valid = Number.isInteger(id) && id > 0;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await raiseConcern({ student_id: id, category, note: note.trim() });
      setNotice("Concern sent. The student's mentor will see it.");
      setStudentId("");
      setNote("");
      onRaised();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} aria-labelledby="raise">
      <h2 id="raise">Raise a concern</h2>
      <p className="muted">
        Tell a student&apos;s mentor about something you noticed. It does not
        start a case or change anything about the student; a person decides what
        to do.
      </p>
      <label htmlFor="student">Student ID</label>
      <input
        id="student"
        type="number"
        min={1}
        inputMode="numeric"
        value={studentId}
        onChange={(e) => setStudentId(e.target.value)}
      />
      <label htmlFor="category">What is it about?</label>
      <select
        id="category"
        value={category}
        onChange={(e) => setCategory(e.target.value as ConcernCategory)}
      >
        {CATEGORIES.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>
      <label htmlFor="note">Note (optional)</label>
      <textarea
        id="note"
        rows={4}
        maxLength={NOTE_LIMIT}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <p className="muted small">
        {note.length}/{NOTE_LIMIT}. Keep to what you saw. Only the mentor and
        the head of department can read it.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <button type="submit" disabled={busy || !valid}>
        Send to the mentor
      </button>
    </form>
  );
}

function ConcernList({ role, refresh }: { role: Role; refresh: number }) {
  const reviewer = role !== "faculty";
  const [page, setPage] = useState<ConcernPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [openOnly, setOpenOnly] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setPage(await loadConcerns({ openOnly, limit: PAGE_SIZE, offset }));
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }, [openOnly, offset]);

  useEffect(() => {
    void load();
  }, [load, refresh]);

  const acknowledge = async (concern: Concern) => {
    setBusy(concern.id);
    try {
      await acknowledgeConcern(concern.id);
      await load();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(null);
    }
  };

  const heading = reviewer ? "Concerns about your students" : "Your concerns";
  return (
    <section aria-labelledby="list">
      <h2 id="list">{heading}</h2>
      {reviewer && (
        <label className="check">
          <input
            type="checkbox"
            checked={openOnly}
            onChange={(e) => {
              setOffset(0);
              setOpenOnly(e.target.checked);
            }}
          />
          <span>Show only concerns I have not acknowledged</span>
        </label>
      )}
      {error && <p role="alert">{error}</p>}
      {!page ? (
        <p className="muted">Loading concerns…</p>
      ) : page.total === 0 ? (
        <p>
          {reviewer
            ? "No concerns to show."
            : "You have not raised any concerns."}
        </p>
      ) : (
        <>
          <ul className="cards">
            {page.items.map((c) => (
              <li key={c.id} className="card">
                <span className="row">
                  <strong>
                    Student {c.student_id} · {categoryLabel(c.category)}
                  </strong>
                  <span className="muted small">{c.raised_on}</span>
                </span>
                {c.note && <span className="note">{c.note}</span>}
                <span className="row muted small">
                  <span>
                    {reviewer && c.raised_by
                      ? `Raised by ${c.raised_by}. `
                      : ""}
                    {c.acknowledged
                      ? reviewer && c.acknowledged_by
                        ? `Acknowledged by ${c.acknowledged_by} on ${c.acknowledged_on}.`
                        : "Seen by the mentor."
                      : "Not acknowledged yet."}
                  </span>
                  {reviewer && !c.acknowledged && (
                    <button
                      type="button"
                      disabled={busy === c.id}
                      onClick={() => acknowledge(c)}
                    >
                      Acknowledge
                    </button>
                  )}
                </span>
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
      )}
    </section>
  );
}

function Concerns() {
  const { role } = useSession();
  const [refresh, setRefresh] = useState(0);
  if (role === null) return null;
  return (
    <>
      {role === "faculty" && (
        <RaiseForm onRaised={() => setRefresh((n) => n + 1)} />
      )}
      <ConcernList role={role} refresh={refresh} />
    </>
  );
}

export default function ConcernsPage() {
  return (
    <AppShell roles={["faculty", "mentor", "staff"]} title="Concerns">
      <Concerns />
    </AppShell>
  );
}
