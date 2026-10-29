import { expect, test } from "@playwright/test";

import { FakeApi, appAlert, makeCase, signIn } from "./fake-api";

function cases() {
  return [
    makeCase(1, { mentor_id: "m1", state: "drafted", band: "red" }),
    makeCase(2, {
      mentor_id: "m1",
      state: "in_review",
      band: "amber",
      overdue: true,
    }),
    makeCase(3, { mentor_id: "m2", state: "new", band: "red", overdue: true }),
    makeCase(4, { mentor_id: "m2", state: "resolved", band: "red" }),
  ];
}

function figure(page: import("@playwright/test").Page, label: string) {
  return page
    .locator("dt", { hasText: label })
    .locator("xpath=following-sibling::dd[1]");
}

for (const role of ["staff", "admin"] as const) {
  test.describe(`overview as ${role}`, () => {
    test("shows counts by band, stage and mentor, and ignores closed cases", async ({
      page,
    }) => {
      const api = new FakeApi(cases(), role);
      api.unassigned = 7;
      await api.install(page);
      await signIn(page, role, "boss");
      await page.goto("/overview");

      await expect(figure(page, "Open cases")).toHaveText("3");
      await expect(figure(page, "Overdue")).toHaveText("2");
      await expect(figure(page, "Red")).toHaveText("2");
      await expect(figure(page, "Amber")).toHaveText("1");
      await expect(figure(page, "Students without a mentor")).toHaveText("7");

      const stage = page.getByRole("row", { name: /^Follow-up review/ });
      await expect(stage).toContainText("1");
      await expect(page.getByRole("row", { name: /^Escalated/ })).toContainText(
        "0",
      );
      await expect(page.getByRole("row", { name: /^m1/ })).toHaveText(
        /m1\s*2\s*1/,
      );
      await expect(page.getByRole("row", { name: /^m2/ })).toHaveText(
        /m2\s*1\s*1/,
      );
    });

    test("never shows a student, a score or a probability", async ({
      page,
    }) => {
      const api = new FakeApi(cases(), role);
      await api.install(page);
      await signIn(page, role, "boss");
      await page.goto("/overview");
      await expect(figure(page, "Open cases")).toBeVisible();
      const body = (await page.locator("main").innerText()).toLowerCase();
      for (const word of ["probab", "score", "student id", "name"])
        expect(body).not.toContain(word);
    });

    test("says so when there are no open cases", async ({ page }) => {
      await new FakeApi([], role).install(page);
      await signIn(page, role, "boss");
      await page.goto("/overview");
      await expect(page.getByText("No open cases.")).toBeVisible();
      await expect(figure(page, "Open cases")).toHaveText("0");
    });

    test("shows the server's error", async ({ page }) => {
      const api = new FakeApi(cases(), role);
      await api.install(page);
      await signIn(page, role, "boss");
      api.failNext(500, null, 2);
      await page.goto("/overview");
      await expect(appAlert(page)).toContainText("Could not load the overview");
    });

    test("a hostile mentor id is shown as text", async ({ page }) => {
      const api = new FakeApi(
        [makeCase(1, { mentor_id: "<img src=x onerror=alert(1)>" })],
        role,
      );
      await api.install(page);
      await signIn(page, role, "boss");
      await page.goto("/overview");
      await expect(
        page.getByText("<img src=x onerror=alert(1)>"),
      ).toBeVisible();
      await expect(page.locator("main img")).toHaveCount(0);
    });

    test("has an Overview link and fits a phone", async ({ page }) => {
      const api = new FakeApi(cases(), role);
      await api.install(page);
      await signIn(page, role, "boss");
      await page.setViewportSize({ width: 375, height: 700 });
      await page.goto("/caseload");
      await page.getByRole("link", { name: "Overview" }).click();
      await expect(
        page.getByRole("heading", { name: "Department overview" }),
      ).toBeVisible();
      await expect(figure(page, "Open cases")).toBeVisible();
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  });
}

for (const role of ["mentor", "faculty"] as const) {
  test(`${role} gets no Overview link and makes no request`, async ({
    page,
  }) => {
    const api = new FakeApi(cases(), role);
    await api.install(page);
    await signIn(page, role);
    await page.goto("/overview");
    await expect(appAlert(page)).toHaveText(
      "This screen is not available for your role.",
    );
    await expect(page.getByRole("link", { name: "Overview" })).toHaveCount(0);
    expect(api.requests.filter((r) => r.path === "/api/overview")).toHaveLength(
      0,
    );
  });
}
