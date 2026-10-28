"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession } from "@/lib/use-session";

// The landing page only routes: signed-out visitors to /login, case readers to the caseload.
export default function Home() {
  const router = useRouter();
  const { ready, role } = useSession();

  useEffect(() => {
    if (!ready) return;
    if (role === null) router.replace("/login");
    else if (role !== "faculty") router.replace("/caseload");
  }, [ready, role, router]);

  if (ready && role === "faculty") {
    return (
      <main className="page">
        <h1>Student Risk</h1>
        <p>There are no screens for your role yet.</p>
      </main>
    );
  }
  return <p className="muted pad">Loading…</p>;
}
