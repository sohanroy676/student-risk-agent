// One journey per role, start to finish in a single session. The screens are tested one by one in
// the other specs; these check that a role can do its whole job and cannot reach anyone else's.

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { FakeApi, appAlert, makeCase, makeConcern, signIn } from "./fake-api";

const NOT_AVAILABLE = "This screen is not available for your role.";

function cases() {
  return [
    makeCase(1, { mentor_id: "m1", state: "drafted", band: "red" }),
    makeCase(2, { mentor_id: "m2", state: "new", band: "amber" }),
    makeCase(4, { mentor_id: "m2", state: "escalated", due_on: null }),
  ];
}

/** Open each path and check the role is turned away without the app asking the API for anything. */
async function assertTurnedAway(page: Page, api: FakeApi, paths: string[]) {
  for (const path of paths) {
    const before = api.requests.length;
    await page.goto(path);
    await expect(appAlert(page)).toHaveText(NOT_AVAILABLE);
    expect(api.requests.slice(before)).toEqual([]);
  }
}

test("faculty journey: raise a concern and nothing else", async ({ page }) => {
  const api = new FakeApi(cases(), "faculty");
  await api.install(page);
  await signIn(page, "faculty", "f1");

  await page.goto("/");
  await expect(page).toHaveURL(/\/concerns$/);
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link")).toHaveText(["Concerns"]);

  await page.getByLabel("Student ID").fill("10");
  await page.getByLabel("What is it about?").selectOption("attendance");
  await page.getByLabel("Note (optional)").fill("Missed three labs");
  await page.getByRole("button", { name: "Send to the mentor" }).click();
  await expect(page.getByText("Concern sent.")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Your concerns" }),
  ).toContainText("Missed three labs");

  await assertTurnedAway(page, api, [
    "/caseload",
    "/followups",
    "/escalations",
    "/overview",
    "/models",
    "/admin/assignments",
    "/admin/nightly",
    "/admin/audit",
  ]);
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/probab|score|band/i);
});

test("mentor journey: review a case, acknowledge a concern, reach nothing administrative", async ({
  page,
}) => {
  const api = new FakeApi(cases(), "mentor");
  api.concerns = [makeConcern(1, { student_id: 10 })];
  await api.install(page);
  await signIn(page, "mentor", "m1");

  await page.goto("/");
  await expect(page).toHaveURL(/\/caseload$/);
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link")).toHaveText([
    "Caseload",
    "Follow-ups",
    "Escalations",
    "Concerns",
  ]);

  await page.getByRole("link", { name: /Student 10/ }).click();
  await page.getByLabel("Draft message").fill("Can we talk on Friday?");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Draft saved.")).toBeVisible();
  await page.getByRole("button", { name: "Approve draft" }).click();
  await expect(page.getByText("Approve draft: done.")).toBeVisible();
  await expect(page.getByText("Monitoring")).toBeVisible();

  await page.getByRole("link", { name: "Concerns" }).click();
  await page.getByRole("button", { name: "Acknowledge" }).click();
  await expect(page.getByRole("button", { name: "Acknowledge" })).toHaveCount(
    0,
  );
  expect(api.calls("POST", "/api/concerns/1/acknowledge")).toHaveLength(1);

  await assertTurnedAway(page, api, [
    "/overview",
    "/models",
    "/admin/assignments",
    "/admin/nightly",
    "/admin/audit",
  ]);
});

test("staff journey: see the department, resolve an escalation, see the count fall", async ({
  page,
}) => {
  const api = new FakeApi(cases(), "staff");
  await api.install(page);
  await signIn(page, "staff", "hod");

  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link")).toHaveText([
    "Caseload",
    "Follow-ups",
    "Escalations",
    "Concerns",
    "Overview",
  ]);

  await nav.getByRole("link", { name: "Overview" }).click();
  await expect(page.locator("dt", { hasText: "Open cases" })).toBeVisible();
  await expect(page.getByRole("row", { name: /^Escalated/ })).toHaveText(
    /Escalated\s*1/,
  );

  await nav.getByRole("link", { name: "Escalations" }).click();
  await page.getByRole("link", { name: /Student 40/ }).click();
  await page.getByRole("button", { name: "Mark resolved" }).click();
  await expect(page.getByText("Mark resolved: done.")).toBeVisible();

  await nav.getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("row", { name: /^Escalated/ })).toHaveText(
    /Escalated\s*0/,
  );
  await expect(
    page
      .locator("dt", { hasText: "Open cases" })
      .locator("xpath=following-sibling::dd[1]"),
  ).toHaveText("2");

  await assertTurnedAway(page, api, [
    "/models",
    "/admin/assignments",
    "/admin/nightly",
    "/admin/audit",
  ]);
});

test("admin journey: read the cases, move a student to another mentor, see it everywhere", async ({
  page,
}) => {
  const api = new FakeApi(cases(), "admin");
  api.nightlyRun = {
    seq: 5,
    at: "2026-03-03T01:00:00+00:00",
    action: "nightly.run",
    detail: { cases_opened: 2 },
  };
  api.auditLog = [
    {
      seq: 1,
      at: "2026-03-03T01:00:00+00:00",
      actor_kind: "system",
      actor_id: null,
      action: "nightly.run",
      subject_kind: "pipeline",
      subject_ref: "2026-03-02",
      hash_prefix: "abc123def456",
    },
  ];
  await api.install(page);
  await signIn(page, "admin", "root");

  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link")).toHaveText([
    "Caseload",
    "Follow-ups",
    "Escalations",
    "Overview",
    "Models",
    "Assignments",
    "Nightly run",
    "Audit",
  ]);

  // admin reads cases but cannot act on them
  await page.getByRole("link", { name: /Student 10/ }).click();
  await expect(page.getByRole("button", { name: "Approve draft" })).toHaveCount(
    0,
  );
  await expect(page.getByRole("button", { name: "Mark resolved" })).toHaveCount(
    0,
  );

  await nav.getByRole("link", { name: "Assignments" }).click();
  await page.getByLabel("Student ID").fill("10");
  await page.getByLabel("Mentor ID").fill("m9");
  await page.getByRole("button", { name: "Save assignment" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Student 10: Assigned; 1 open case moved.",
  );

  await nav.getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("row", { name: /^m9/ })).toHaveText(/m9\s*1/);
  await expect(page.getByRole("row", { name: /^m1/ })).toHaveCount(0);

  await nav.getByRole("link", { name: "Nightly run" }).click();
  await expect(page.getByText("The last night finished.")).toBeVisible();

  await nav.getByRole("link", { name: "Audit" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByRole("button", { name: "Check now" }).click();
  await expect(page.getByRole("status")).toContainText("Intact");

  await nav.getByRole("link", { name: "Models" }).click();
  await expect(page.getByText("No model has been registered")).toBeVisible();
});
