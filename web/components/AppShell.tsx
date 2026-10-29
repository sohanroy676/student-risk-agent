"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { clearToken } from "@/lib/session";
import type { Role } from "@/lib/types";
import { useSession } from "@/lib/use-session";

interface NavItem {
  href: string;
  label: string;
  roles: Role[];
}

// Only screens that exist are listed; each is also protected by the API, not just hidden here.
const NAV: NavItem[] = [
  { href: "/caseload", label: "Caseload", roles: ["mentor", "staff", "admin"] },
  {
    href: "/followups",
    label: "Follow-ups",
    roles: ["mentor", "staff", "admin"],
  },
  {
    href: "/escalations",
    label: "Escalations",
    roles: ["mentor", "staff", "admin"],
  },
  {
    href: "/concerns",
    label: "Concerns",
    roles: ["faculty", "mentor", "staff"],
  },
  { href: "/overview", label: "Overview", roles: ["staff", "admin"] },
  { href: "/models", label: "Models", roles: ["admin"] },
  { href: "/admin/assignments", label: "Assignments", roles: ["admin"] },
  { href: "/admin/nightly", label: "Nightly run", roles: ["admin"] },
  { href: "/admin/audit", label: "Audit", roles: ["admin"] },
];

const ROLE_LABEL: Record<Role, string> = {
  admin: "Administrator",
  staff: "HoD / counsellor",
  mentor: "Mentor",
  faculty: "Faculty",
};

/**
 * Page frame for signed-in screens. Sends visitors without a valid sign-in to /login and shows
 * a plain message to roles that may not use the screen.
 */
export default function AppShell({
  roles,
  title,
  children,
}: {
  roles: Role[];
  title: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { ready, role, subject } = useSession();

  useEffect(() => {
    if (ready && role === null) router.replace("/login");
  }, [ready, role, router]);

  if (!ready || role === null) return <p className="muted pad">Loading…</p>;

  const signOut = () => {
    clearToken();
    router.replace("/login");
  };

  return (
    <>
      <header className="bar">
        <nav aria-label="Main">
          <strong className="brand">Student Risk</strong>
          {NAV.filter((item) => item.roles.includes(role)).map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="who">
          <span>
            {ROLE_LABEL[role]}
            {subject ? ` · ${subject}` : ""}
          </span>
          <button type="button" className="link" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="page">
        <h1>{title}</h1>
        {roles.includes(role) ? (
          children
        ) : (
          <p role="alert">This screen is not available for your role.</p>
        )}
      </main>
    </>
  );
}
