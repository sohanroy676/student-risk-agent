"use client";

import AppShell from "@/components/AppShell";
import CaseList from "@/components/CaseList";

export default function FollowUpsPage() {
  return (
    <AppShell roles={["mentor", "staff", "admin"]} title="Follow-up review">
      <p>
        A week has passed since the message was approved. For each case, decide
        whether to keep monitoring, mark it resolved, or hand it to a person.
        After the third round the case goes to a person automatically.
      </p>
      <CaseList
        state="in_review"
        intro="Oldest due first."
        empty="No cases are waiting for a follow-up review."
        noun={["case to review", "cases to review"]}
      />
    </AppShell>
  );
}
