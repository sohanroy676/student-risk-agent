"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession } from "@/lib/use-session";

// The landing page only routes: signed-out visitors to /login, faculty to their concerns,
// everyone else to the caseload.
export default function Home() {
  const router = useRouter();
  const { ready, role } = useSession();

  useEffect(() => {
    if (!ready) return;
    if (role === null) router.replace("/login");
    else router.replace(role === "faculty" ? "/concerns" : "/caseload");
  }, [ready, role, router]);

  return <p className="muted pad">Loading…</p>;
}
