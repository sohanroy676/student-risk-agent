"use client";

import AppShell from "@/components/AppShell";
import CaseList from "@/components/CaseList";

export default function EscalationsPage() {
  return (
    <AppShell roles={["mentor", "staff", "admin"]} title="Escalations">
      <p>
        These cases were handed to a person, by a mentor or after three rounds
        without improvement. The system decides nothing about the student: a
        person reviews each case and marks it resolved.
      </p>
      <CaseList
        state="escalated"
        intro="Oldest first."
        empty="No cases are escalated right now."
        noun={["escalated case", "escalated cases"]}
      />
    </AppShell>
  );
}
