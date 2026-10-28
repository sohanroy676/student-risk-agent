"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import { ApiError, loadReleases } from "@/lib/api";
import { gateSummary, number3 } from "@/lib/models";
import type { ModelRelease } from "@/lib/types";

function Releases() {
  const [releases, setReleases] = useState<ModelRelease[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    loadReleases()
      .then((data) => current && setReleases(data))
      .catch(
        (e: unknown) =>
          current && setError(e instanceof ApiError ? e.message : "failed"),
      );
    return () => {
      current = false;
    };
  }, []);

  if (error) return <p role="alert">Could not load models: {error}.</p>;
  if (!releases) return <p className="muted">Loading models…</p>;
  if (releases.length === 0) {
    return (
      <p>
        No model has been registered yet. Run the release command to add one.
      </p>
    );
  }
  return (
    <>
      <p className="muted">
        Newest first. Only a release the gate passes (or a named sign-off
        covers) can go live.
      </p>
      <ul className="cards">
        {releases.map((r) => (
          <li key={r.release}>
            <Link href={`/models/${r.release}`} className="card">
              <span className="row">
                <strong>Release {r.release}</strong>
                {r.in_production ? (
                  <span className="badge badge-ok">In production</span>
                ) : (
                  <span className="muted">{gateSummary(r)}</span>
                )}
              </span>
              <span className="row muted">
                <span>Week-4 AUC {number3(r.metrics?.auc_week4)}</span>
                <span>Calibration error {number3(r.metrics?.ece)}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

export default function ModelsPage() {
  return (
    <AppShell roles={["admin"]} title="Models and fairness">
      <Releases />
    </AppShell>
  );
}
