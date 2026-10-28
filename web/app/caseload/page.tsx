"use client";

import AppShell from "@/components/AppShell";
import CaseList from "@/components/CaseList";

export default function CaseloadPage() {
  return (
    <AppShell roles={["mentor", "staff", "admin"]} title="Caseload">
      <CaseList
        intro="Most urgent first."
        empty="No open cases. Nothing needs attention right now."
        noun={["open case", "open cases"]}
      />
    </AppShell>
  );
}
