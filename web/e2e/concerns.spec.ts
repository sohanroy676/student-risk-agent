import { expect, test } from "@playwright/test";

import { FakeApi, appAlert, makeCase, makeConcern, signIn } from "./fake-api";

function apiWith(...concerns: ReturnType<typeof makeConcern>[]) {
  const api = new FakeApi([makeCase(1)]);
  api.concerns = concerns;
  return api;
}

test.describe("faculty", () => {
  test("raise a concern and see it in their own list", async ({ page }) => {
    const api = apiWith();
    await api.install(page);
    await signIn(page, "faculty", "f1");
    await page.goto("/");

    await expect(page).toHaveURL(/\/concerns$/);
    await expect(
      page.getByText("You have not raised any concerns."),
    ).toBeVisible();
    const send = page.getByRole("button", { name: "Send to the mentor" });
    await expect(send).toBeDisabled(); // a student ID is needed first

    await page.getByLabel("Student ID").fill("42");
    await page.getByLabel("What is it about?").selectOption("wellbeing");
    await page
      .getByLabel("Note (optional)")
      .fill("  Seemed very tired this week  ");
    await send.click();

    await expect(
      page.getByText("Concern sent. The student's mentor will see it."),
    ).toBeVisible();
    expect(api.calls("POST", "/api/concerns")[0].body).toEqual({
      student_id: 42,
      category: "wellbeing",
      note: "Seemed very tired this week",
    });
    const list = page.getByRole("region", { name: "Your concerns" });
    await expect(list).toContainText("Student 42 · Wellbeing");
    await expect(list).toContainText("Seemed very tired this week");
    await expect(list).toContainText("Not acknowledged yet.");
    await expect(page.getByLabel("Student ID")).toHaveValue(""); // ready for the next one
  });

  test("the note is optional", async ({ page }) => {
    const api = apiWith();
    await api.install(page);
    await signIn(page, "faculty", "f1");
    await page.goto("/concerns");
    await page.getByLabel("Student ID").fill("7");
    await page.getByRole("button", { name: "Send to the mentor" }).click();
    await expect(page.getByText("Concern sent.")).toBeVisible();
    expect(api.calls("POST", "/api/concerns")[0].body).toMatchObject({
      student_id: 7,
      note: "",
    });
  });

  test("an unknown student is explained and nothing is listed", async ({
    page,
  }) => {
    await apiWith().install(page);
    await signIn(page, "faculty", "f1");
    await page.goto("/concerns");
    await page.getByLabel("Student ID").fill("999");
    await page.getByRole("button", { name: "Send to the mentor" }).click();
    await expect(appAlert(page)).toHaveText("student not found");
    await expect(
      page.getByText("You have not raised any concerns."),
    ).toBeVisible();
  });

  test("the daily limit is shown as the server words it", async ({ page }) => {
    const api = apiWith();
    await api.install(page);
    await signIn(page, "faculty", "f1");
    await page.goto("/concerns");
    await expect(
      page.getByText("You have not raised any concerns."),
    ).toBeVisible();
    api.failNext(429, "daily limit of concerns reached");
    await page.getByLabel("Student ID").fill("5");
    await page.getByRole("button", { name: "Send to the mentor" }).click();
    await expect(appAlert(page)).toHaveText("daily limit of concerns reached");
  });

  test("the note box stops at the limit and counts characters", async ({
    page,
  }) => {
    await apiWith().install(page);
    await signIn(page, "faculty", "f1");
    await page.goto("/concerns");
    await page.getByLabel("Note (optional)").fill("x".repeat(600));
    await expect(page.getByLabel("Note (optional)")).toHaveValue(
      "x".repeat(500),
    );
    await expect(page.getByText("500/500.")).toBeVisible();
  });

  test("never see who acknowledged, a case, a band or a score", async ({
    page,
  }) => {
    await apiWith(
      makeConcern(1, {
        raised_by: null,
        acknowledged: true,
        acknowledged_by: null,
        acknowledged_on: null,
      }),
    ).install(page);
    await signIn(page, "faculty", "f1");
    await page.goto("/concerns");
    const main = page.locator("main");
    await expect(main).toContainText("Seen by the mentor.");
    await expect(main).not.toContainText(/band|score|probab|case \d/i);
    await expect(page.getByRole("button", { name: "Acknowledge" })).toHaveCount(
      0,
    );
  });

  test("concern text is shown as text, never as HTML", async ({ page }) => {
    await apiWith(
      makeConcern(1, { note: "<img src=x onerror=window.__pwned=1>" }),
    ).install(page);
    await signIn(page, "faculty", "f1");
    await page.goto("/concerns");
    await expect(
      page.getByText("<img src=x onerror=window.__pwned=1>"),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => (window as unknown as { __pwned?: number }).__pwned,
      ),
    ).toBeUndefined();
  });
});

test.describe("mentors and staff", () => {
  for (const role of ["mentor", "staff"] as const) {
    test(`${role} read and acknowledge concerns, with who raised them`, async ({
      page,
    }) => {
      const api = apiWith(
        makeConcern(2, { student_id: 20, category: "wellbeing" }),
        makeConcern(1, {
          acknowledged: true,
          acknowledged_by: "m1",
          acknowledged_on: "2026-03-03",
        }),
      );
      await api.install(page);
      await signIn(page, role, "m1");
      await page.goto("/concerns");

      const list = page.getByRole("region", {
        name: "Concerns about your students",
      });
      await expect(list).toContainText("Student 20 · Wellbeing");
      await expect(list).toContainText("Raised by f1.");
      await expect(list).toContainText("Acknowledged by m1 on 2026-03-03.");
      await expect(
        page.getByRole("heading", { name: "Raise a concern" }),
      ).toHaveCount(0);

      await page.getByRole("button", { name: "Acknowledge" }).click();
      await expect(list).not.toContainText("Not acknowledged yet.");
      await expect(
        page.getByRole("button", { name: "Acknowledge" }),
      ).toHaveCount(0);
      expect(api.calls("POST", "/api/concerns/2/acknowledge")).toHaveLength(1);
    });
  }

  test("the filter shows only what has not been acknowledged", async ({
    page,
  }) => {
    const api = apiWith(
      makeConcern(2, { student_id: 20 }),
      makeConcern(1, {
        student_id: 10,
        acknowledged: true,
        acknowledged_by: "m1",
        acknowledged_on: "2026-03-03",
      }),
    );
    await api.install(page);
    await signIn(page, "mentor", "m1");
    await page.goto("/concerns");
    await expect(page.getByText("Student 10")).toBeVisible();
    await page.getByLabel("Show only concerns I have not acknowledged").check();
    await expect(page.getByText("Student 10")).toHaveCount(0);
    await expect(page.getByText("Student 20")).toBeVisible();
  });

  test("an empty list says so", async ({ page }) => {
    await apiWith().install(page);
    await signIn(page, "mentor", "m1");
    await page.goto("/concerns");
    await expect(page.getByText("No concerns to show.")).toBeVisible();
  });

  test("a refused acknowledgement shows the reason", async ({ page }) => {
    const api = apiWith(makeConcern(2));
    await api.install(page);
    await signIn(page, "mentor", "m1");
    await page.goto("/concerns");
    await expect(page.getByText("Student 20")).toBeVisible();
    api.failNext(409, "concern already acknowledged");
    await page.getByRole("button", { name: "Acknowledge" }).click();
    await expect(appAlert(page)).toHaveText("concern already acknowledged");
  });
});

test.describe("admin", () => {
  test("has no concerns screen and no request is made", async ({ page }) => {
    const api = apiWith(makeConcern(1));
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/caseload");
    await expect(page.getByRole("link", { name: "Concerns" })).toHaveCount(0);
    await page.goto("/concerns");
    await expect(
      page.getByText("This screen is not available for your role."),
    ).toBeVisible();
    expect(api.calls("GET", "/api/concerns")).toHaveLength(0);
  });
});

test.describe("small screens", () => {
  test.use({ viewport: { width: 375, height: 667 } });

  for (const role of ["faculty", "mentor"] as const) {
    test(`${role} concerns page does not scroll sideways on a phone`, async ({
      page,
    }) => {
      await apiWith(
        makeConcern(1, { note: "word ".repeat(100).trim() }),
        makeConcern(2, { note: "x".repeat(200) }),
      ).install(page);
      await signIn(page, role, "u1");
      await page.goto("/concerns");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText(/Student 10/).first()).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});
