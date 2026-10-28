import { expect, test } from "@playwright/test";

import { FakeApi, appAlert, makeCase, signIn } from "./fake-api";

const cases = () => [
  makeCase(1, { state: "drafted" }),
  makeCase(2, { state: "in_review", due_on: "2026-03-04", cycle: 1 }),
  makeCase(3, { state: "in_review", overdue: true, band: "amber" }),
  makeCase(4, { state: "escalated", due_on: null }),
  makeCase(5, { state: "monitoring" }),
  makeCase(6, { state: "resolved" }),
];

test.describe("follow-up review", () => {
  test("lists only the cases waiting for a review, with the overdue ones marked", async ({
    page,
  }) => {
    await new FakeApi(cases()).install(page);
    await signIn(page, "mentor");
    await page.goto("/followups");

    await expect(
      page.getByRole("heading", { name: "Follow-up review" }),
    ).toBeVisible();
    await expect(page.getByText("2 cases to review.")).toBeVisible();
    const cards = page.getByRole("link", { name: /Student/ });
    await expect(cards).toHaveCount(2);
    await expect(cards.nth(0)).toContainText("Student 20");
    await expect(cards.nth(0)).toContainText("Follow-up review");
    await expect(cards.nth(1)).toContainText("overdue");
    await expect(page.getByText("Student 10")).toHaveCount(0); // a draft is not a review
    await expect(page.getByText("Student 40")).toHaveCount(0);
  });

  test("a mentor continues monitoring and the case leaves the list", async ({
    page,
  }) => {
    const api = new FakeApi(cases());
    await api.install(page);
    await signIn(page, "mentor");
    await page.goto("/followups");
    await page.getByRole("link", { name: /Student 20/ }).click();

    await expect(
      page.getByRole("button", { name: "Continue monitoring" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Mark resolved" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Escalate to a person" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Approve draft" }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Continue monitoring" }).click();
    await expect(page.getByText("Continue monitoring: done.")).toBeVisible();
    expect(api.calls("POST", "/api/cases/2/actions")[0].body).toEqual({
      action: "continue",
    });

    await page.getByRole("link", { name: "Follow-ups" }).click();
    await expect(page.getByText("1 case to review.")).toBeVisible();
    await expect(page.getByText("Student 20")).toHaveCount(0);
  });

  test("says so when no case is waiting", async ({ page }) => {
    await new FakeApi([makeCase(1)]).install(page);
    await signIn(page, "mentor");
    await page.goto("/followups");
    await expect(
      page.getByText("No cases are waiting for a follow-up review."),
    ).toBeVisible();
  });

  test("staff may resolve or escalate a review but not continue it", async ({
    page,
  }) => {
    await new FakeApi(cases(), "staff").install(page);
    await signIn(page, "staff", "hod");
    await page.goto("/cases/2");
    await expect(
      page.getByRole("button", { name: "Mark resolved" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Continue monitoring" }),
    ).toHaveCount(0);
  });
});

test.describe("escalations", () => {
  test("lists only escalated cases and explains that a person decides", async ({
    page,
  }) => {
    await new FakeApi(cases()).install(page);
    await signIn(page, "staff", "hod");
    await page.goto("/escalations");

    await expect(
      page.getByRole("heading", { name: "Escalations" }),
    ).toBeVisible();
    await expect(
      page.getByText("The system decides nothing about the student"),
    ).toBeVisible();
    await expect(page.getByText("1 escalated case.")).toBeVisible();
    const card = page.getByRole("link", { name: /Student 40/ });
    await expect(card).toContainText("Escalated");
    await expect(card).toContainText("No due date");
    await expect(page.getByRole("link", { name: /Student/ })).toHaveCount(1);
  });

  test("staff resolve an escalated case and it leaves the list", async ({
    page,
  }) => {
    const api = new FakeApi(cases(), "staff");
    await api.install(page);
    await signIn(page, "staff", "hod");
    await page.goto("/escalations");
    await page.getByRole("link", { name: /Student 40/ }).click();
    await expect(
      page.getByRole("button", { name: "Escalate to a person" }),
    ).toHaveCount(0); // already escalated
    await page.getByRole("button", { name: "Mark resolved" }).click();
    await expect(page.getByText("Mark resolved: done.")).toBeVisible();
    await page.getByRole("link", { name: "Escalations" }).click();
    await expect(
      page.getByText("No cases are escalated right now."),
    ).toBeVisible();
  });

  test("a mentor escalates a case from the case page and it appears in the list", async ({
    page,
  }) => {
    const api = new FakeApi(cases());
    await api.install(page);
    await signIn(page, "mentor");
    await page.goto("/cases/5");
    await page.getByRole("button", { name: "Escalate to a person" }).click();
    await expect(page.getByText("Escalate to a person: done.")).toBeVisible();
    await page.getByRole("link", { name: "Escalations" }).click();
    await expect(page.getByText("2 escalated cases.")).toBeVisible();
  });

  test("an API error is shown, not a blank page", async ({ page }) => {
    const api = new FakeApi(cases());
    await api.install(page);
    await signIn(page, "mentor");
    api.failNext(403, "not allowed", 2); // twice: the dev server loads twice
    await page.goto("/escalations");
    await expect(appAlert(page)).toContainText("not allowed");
  });
});

test.describe("navigation and roles", () => {
  for (const role of ["mentor", "staff", "admin"] as const) {
    test(`${role} sees the Caseload, Follow-ups and Escalations links`, async ({
      page,
    }) => {
      await new FakeApi(cases(), role).install(page);
      await signIn(page, role, "u1");
      await page.goto("/caseload");
      for (const name of ["Caseload", "Follow-ups", "Escalations"]) {
        await expect(page.getByRole("link", { name })).toBeVisible();
      }
    });
  }

  test("admin can read both lists but gets no action buttons on a review", async ({
    page,
  }) => {
    await new FakeApi(cases(), "admin").install(page);
    await signIn(page, "admin", "root");
    await page.goto("/followups");
    await expect(page.getByText("2 cases to review.")).toBeVisible();
    await page.getByRole("link", { name: /Student 20/ }).click();
    await expect(
      page.getByText("Administrators can read cases but not act on them."),
    ).toBeVisible();
  });

  test("faculty see neither list and the API is not asked for cases", async ({
    page,
  }) => {
    const api = new FakeApi(cases());
    await api.install(page);
    await signIn(page, "faculty", "f1");
    for (const path of ["/followups", "/escalations"]) {
      await page.goto(path);
      await expect(
        page.getByText("This screen is not available for your role."),
      ).toBeVisible();
    }
    await expect(page.getByRole("link", { name: "Follow-ups" })).toHaveCount(0);
    expect(api.calls("GET", "/api/caseload")).toHaveLength(0);
  });

  test("without a sign-in both screens go to the login page", async ({
    page,
  }) => {
    await new FakeApi(cases()).install(page);
    for (const path of ["/followups", "/escalations"]) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/login$/);
    }
  });
});

test.describe("small screens", () => {
  test.use({ viewport: { width: 375, height: 667 } });

  for (const path of ["/followups", "/escalations", "/caseload"]) {
    test(`${path} does not scroll sideways on a phone`, async ({ page }) => {
      await new FakeApi(cases()).install(page);
      await signIn(page, "mentor");
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(
        page.getByRole("link", { name: /Student/ }).first(),
      ).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});
