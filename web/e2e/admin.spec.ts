import { expect, test } from "@playwright/test";

import { FakeApi, appAlert, makeCase, signIn } from "./fake-api";

function admin() {
  return new FakeApi(
    [makeCase(1, { student_id: 10, mentor_id: "m1" })],
    "admin",
  );
}

test.describe("admin assignments", () => {
  test("assigns a mentor and says the open case moved", async ({ page }) => {
    const api = admin();
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/assignments");

    await page.getByLabel("Student ID").fill("10");
    await page.getByLabel("Mentor ID").fill("  m2  ");
    await page.getByRole("button", { name: "Save assignment" }).click();

    await expect(page.getByRole("status")).toHaveText(
      "Student 10: Assigned; 1 open case moved.",
    );
    const [call] = api.calls("PUT", "/api/admin/mentor-assignments/10");
    expect(call.body).toEqual({ mentor_id: "m2" });
  });

  test("saying the same thing twice reports no change", async ({ page }) => {
    await admin().install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/assignments");

    for (let i = 0; i < 2; i++) {
      await page.getByLabel("Student ID").fill("20");
      await page.getByLabel("Mentor ID").fill("m9");
      await page.getByRole("button", { name: "Save assignment" }).click();
    }
    await expect(page.getByRole("status")).toHaveText("Student 20: No change.");
  });

  test("an unknown student shows the server's answer", async ({ page }) => {
    await admin().install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/assignments");

    await page.getByLabel("Student ID").fill("999");
    await page.getByLabel("Mentor ID").fill("m2");
    await page.getByRole("button", { name: "Save assignment" }).click();
    await expect(appAlert(page)).toHaveText("student not found");
  });

  test("bad input never reaches the API", async ({ page }) => {
    const api = admin();
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/assignments");
    const save = page.getByRole("button", { name: "Save assignment" });

    await expect(save).toBeDisabled();
    await page.getByLabel("Mentor ID").fill("m2");
    for (const bad of ["0", "-3", "1.5", "2147483648", ""]) {
      await page.getByLabel("Student ID").fill(bad);
      await expect(save).toBeDisabled();
    }
    await page.getByLabel("Student ID").fill("10");
    await page.getByLabel("Mentor ID").fill("   ");
    await expect(save).toBeDisabled();
    await page.getByLabel("Mentor ID").fill("x".repeat(129));
    await expect(save).toBeDisabled();
    await page.getByLabel("Mentor ID").fill("x".repeat(128));
    await expect(save).toBeEnabled();
    expect(api.calls("PUT", "/api/admin")).toHaveLength(0);
  });

  test("a server refusal is shown as written", async ({ page }) => {
    const api = admin();
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/assignments");

    await page.getByLabel("Student ID").fill("10");
    await page.getByLabel("Mentor ID").fill("m2");
    api.failNext(403, "not allowed");
    await page.getByRole("button", { name: "Save assignment" }).click();
    await expect(appAlert(page)).toHaveText("not allowed");
  });

  for (const role of ["mentor", "staff", "faculty"] as const) {
    test(`${role} sees no assignment form and makes no request`, async ({
      page,
    }) => {
      const api = new FakeApi([], role);
      await api.install(page);
      await signIn(page, role);
      await page.goto("/admin/assignments");
      await expect(appAlert(page)).toHaveText(
        "This screen is not available for your role.",
      );
      await expect(page.getByLabel("Student ID")).toHaveCount(0);
      expect(
        api.requests.filter((r) => r.path.includes("/admin")),
      ).toHaveLength(0);
    });
  }
});

test.describe("admin nightly run", () => {
  test("shows the counts of the last run in plain words", async ({ page }) => {
    const api = admin();
    api.nightlyRun = {
      seq: 7,
      at: "2026-03-03T01:00:12+00:00",
      action: "nightly.run",
      detail: {
        as_of: "2026-03-02",
        students_evaluated: 400,
        cases_opened: 3,
        // not on the list, so never shown
        student_names: "should not appear",
        nested: { a: 1 },
      },
    };
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/nightly");

    await expect(page.getByText("The last night finished.")).toBeVisible();
    await expect(page.getByText("Students evaluated")).toBeVisible();
    await expect(page.getByText("400")).toBeVisible();
    await expect(page.getByText("Cases opened")).toBeVisible();
    await expect(page.getByText("should not appear")).toHaveCount(0);
    await expect(page.getByText("nested")).toHaveCount(0);
  });

  test("a halted night is described as halted", async ({ page }) => {
    const api = admin();
    api.nightlyRun = {
      seq: 8,
      at: "2026-03-04T01:00:00+00:00",
      action: "nightly.halted",
      detail: { cause: "<b>too many rejected rows</b>" },
    };
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/nightly");

    await expect(page.getByText(/stopped before scoring/)).toBeVisible();
    // text only, never markup
    await expect(page.getByText("<b>too many rejected rows</b>")).toBeVisible();
  });

  test("says so when no run is recorded", async ({ page }) => {
    await admin().install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/nightly");
    await expect(page.getByText("No nightly run recorded yet.")).toBeVisible();
  });

  test("shows an error when the run cannot be loaded", async ({ page }) => {
    const api = admin();
    await api.install(page);
    await signIn(page, "admin", "root");
    api.failNext(500, null, 2);
    await page.goto("/admin/nightly");
    await expect(appAlert(page)).toContainText("Could not load the last run");
  });

  for (const role of ["mentor", "staff", "faculty"] as const) {
    test(`${role} makes no request for the run`, async ({ page }) => {
      const api = new FakeApi([], role);
      await api.install(page);
      await signIn(page, role);
      await page.goto("/admin/nightly");
      await expect(appAlert(page)).toHaveText(
        "This screen is not available for your role.",
      );
      expect(
        api.requests.filter((r) => r.path.includes("/admin")),
      ).toHaveLength(0);
    });
  }

  test("admin nav links lead to both screens, other roles do not see them", async ({
    page,
  }) => {
    await admin().install(page);
    await signIn(page, "admin", "root");
    await page.goto("/caseload");
    await page.getByRole("link", { name: "Assignments" }).click();
    await expect(
      page.getByRole("heading", { name: "Mentor assignments" }),
    ).toBeVisible();
    await page.getByRole("link", { name: "Nightly run" }).click();
    await expect(
      page.getByRole("heading", { name: "Last nightly run" }),
    ).toBeVisible();
  });

  test("mentors do not see the admin links", async ({ page }) => {
    await new FakeApi([makeCase(1)], "mentor").install(page);
    await signIn(page, "mentor");
    await page.goto("/caseload");
    await expect(page.getByRole("link", { name: "Assignments" })).toHaveCount(
      0,
    );
    await expect(page.getByRole("link", { name: "Nightly run" })).toHaveCount(
      0,
    );
  });

  test("fits a phone without sideways scrolling", async ({ page }) => {
    const api = admin();
    api.nightlyRun = {
      seq: 1,
      at: "2026-03-03T01:00:12+00:00",
      action: "nightly.run",
      detail: { as_of: "2026-03-02", cases_opened: 3 },
    };
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.setViewportSize({ width: 375, height: 700 });
    for (const path of ["/admin/assignments", "/admin/nightly"]) {
      await page.goto(path);
      await expect(page.locator("main h1")).toBeVisible();
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    }
  });
});
