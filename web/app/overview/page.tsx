"use client";

import { useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import { STATE_LABEL } from "@/lib/actions";
import { ApiError, loadOverview } from "@/lib/api";
import type { CaseState, Overview } from "@/lib/types";

const STATES: CaseState[] = [
  "new",
  "drafted",
  "monitoring",
  "in_review",
  "escalated",
];

function Counts() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    loadOverview()
      .then((o) => current && setData(o))
      .catch(
        (e: unknown) =>
          current && setError(e instanceof ApiError ? e.message : "failed"),
      );
    return () => {
      current = false;
    };
  }, []);

  if (error) return <p role="alert">Could not load the overview: {error}.</p>;
  if (!data) return <p className="muted">Loading the overview…</p>;

  return (
    <>
      <p className="muted">
        Counts only, as of now. A person decides what happens to each case; this
        page decides nothing.
      </p>
      <dl className="facts">
        <div className="row">
          <dt>Open cases</dt>
          <dd>{data.open_cases}</dd>
        </div>
        <div className="row">
          <dt>Overdue</dt>
          <dd>{data.overdue}</dd>
        </div>
        <div className="row">
          <dt>Red</dt>
          <dd>{data.by_band.red ?? 0}</dd>
        </div>
        <div className="row">
          <dt>Amber</dt>
          <dd>{data.by_band.amber ?? 0}</dd>
        </div>
        <div className="row">
          <dt>Students without a mentor</dt>
          <dd>{data.unassigned_students}</dd>
        </div>
      </dl>

      <h2>Open cases by stage</h2>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Stage</th>
              <th scope="col">Cases</th>
            </tr>
          </thead>
          <tbody>
            {STATES.map((s) => (
              <tr key={s}>
                <th scope="row">{STATE_LABEL[s]}</th>
                <td>{data.by_state[s] ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>By mentor</h2>
      {data.by_mentor.length === 0 ? (
        <p className="muted">No open cases.</p>
      ) : (
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Mentor</th>
                <th scope="col">Open</th>
                <th scope="col">Overdue</th>
              </tr>
            </thead>
            <tbody>
              {data.by_mentor.map((m) => (
                <tr key={m.mentor_id}>
                  <th scope="row">{m.mentor_id}</th>
                  <td>{m.open}</td>
                  <td>{m.overdue}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function OverviewPage() {
  return (
    <AppShell roles={["staff", "admin"]} title="Department overview">
      <Counts />
    </AppShell>
  );
}
