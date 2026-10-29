"use client";

import { useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import { runRows } from "@/lib/admin";
import { ApiError, loadLatestRun } from "@/lib/api";
import type { NightlyRun } from "@/lib/types";

function LatestRun() {
  const [run, setRun] = useState<NightlyRun | null>(null);
  const [none, setNone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    loadLatestRun()
      .then((data) => current && setRun(data))
      .catch((e: unknown) => {
        if (!current) return;
        if (e instanceof ApiError && e.status === 404) setNone(true);
        else setError(e instanceof ApiError ? e.message : "failed");
      });
    return () => {
      current = false;
    };
  }, []);

  if (error) return <p role="alert">Could not load the last run: {error}.</p>;
  if (none) return <p>No nightly run recorded yet.</p>;
  if (!run) return <p className="muted">Loading the last run…</p>;

  const halted = run.action === "nightly.halted";
  return (
    <>
      <p>
        {halted
          ? "The last night stopped before scoring because the data failed its checks."
          : "The last night finished."}{" "}
        <span className="muted">
          Recorded {new Date(run.at).toLocaleString()}.
        </span>
      </p>
      <dl className="facts">
        {runRows(run.detail).map(([label, value]) => (
          <div key={label} className="row">
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

export default function NightlyPage() {
  return (
    <AppShell roles={["admin"]} title="Last nightly run">
      <LatestRun />
    </AppShell>
  );
}
