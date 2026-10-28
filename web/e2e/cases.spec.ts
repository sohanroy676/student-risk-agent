import { expect, test } from "@playwright/test";

import { FakeApi, appAlert, makeCase, signIn } from "./fake-api";

test.describe("mentor", () => {
  test("sees the open cases in the order the API gives, with the band in words", async ({
    page,
  }) => {
    const api = new FakeApi([
      makeCase(2, { band: "amber", state: "new", due_on: null }),
      makeCase(1),
      makeCase(3, { state: "resolved" }),
    ]);
    await api.install(page);
    await signIn(page, "mentor");
    await page.goto("/caseload");

    await expect(page.getByText("2 open cases")).toBeVisible();
    const cards = page.getByRole("link", { name: /Student/ });
    await expect(cards).toHaveCount(2);
    await expect(cards.nth(0)).toContainText("Student 20");
    await expect(cards.nth(0)).toContainText("Amber band");
    await expect(cards.nth(1)).toContainText("Red band");
    await expect(page.getByText("Student 30")).toHaveCount(0); // resolved cases are not listed
    await expect(page.locator("body")).not.toContainText(/probab|score/i);
  });

  test("says so when there is nothing to do", async ({ page }) => {
    await new FakeApi([]).install(page);
    await signIn(page, "mentor");
    await page.goto("/caseload");
    await expect(page.getByText("No open cases")).toBeVisible();
  });

  test("opens a case, edits the draft and approves it, in that order", async ({
    page,
  }) => {
    const api = new FakeApi([makeCase(1)]);
    await api.install(page);
    await signIn(page, "mentor");
    await page.goto("/caseload");
    await page.getByRole("link", { name: /Student 10/ }).click();

    await expect(
      page.getByRole("heading", { name: /Student 10/ }),
    ).toBeVisible();
    await expect(page.getByText("Attendance is 40% so far")).toBeVisible();
    await expect(
      page.getByText("Nothing is sent until you approve it."),
    ).toBeVisible();

    const draft = page.getByLabel("Draft message");
    const approve = page.getByRole("button", { name: "Approve draft" });
    await expect(approve).toBeEnabled();

    await draft.fill("Can we talk on Friday?");
    await expect(approve).toBeDisabled(); // unsaved wording must not be approved by mistake
    await expect(
      page.getByText("Save your changes before approving"),
    ).toBeVisible();
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Draft saved.")).toBeVisible();
    expect(api.calls("PUT", "/api/cases/1/draft")[0].body).toEqual({
      message: "Can we talk on Friday?",
    });

    await expect(approve).toBeEnabled();
    await approve.click();
    await expect(page.getByText("Approve draft: done.")).toBeVisible();
    await expect(page.getByText("Monitoring")).toBeVisible();
    await expect(page.getByText("2026-03-03 by m1")).toBeVisible();
    // once approved the wording is read-only
    await expect(page.getByLabel("Draft message")).toHaveCount(0);
    await expect(page.getByText("Can we talk on Friday?")).toBeVisible();
    expect(api.calls("POST", "/api/cases/1/actions")[0].body).toEqual({
      action: "approve",
    });
  });

  test("shows the API's reason when a move is refused", async ({ page }) => {
    const api = new FakeApi([makeCase(1)]);
    await api.install(page);
    await signIn(page, "mentor");
    await page.goto("/cases/1");
    await expect(
      page.getByRole("heading", { name: /Student 10/ }),
    ).toBeVisible();
    api.failNext(409, "cannot approve a monitoring case"); // the next call is the click, not the load
    await page.getByRole("button", { name: "Approve draft" }).click();
    await expect(appAlert(page)).toHaveText("cannot approve a monitoring case");
  });

  test("a case that is not theirs reads as not found", async ({ page }) => {
    await new FakeApi([makeCase(1)]).install(page);
    await signIn(page, "mentor");
    await page.goto("/cases/99");
    await expect(appAlert(page)).toContainText("case not found");
  });

  test("a case still waiting for its draft says so and offers no editor", async ({
    page,
  }) => {
    await new FakeApi([makeCase(1, { state: "new", draft: null })]).install(
      page,
    );
    await signIn(page, "mentor");
    await page.goto("/cases/1");
    await expect(
      page.getByText("A draft will be prepared tonight."),
    ).toBeVisible();
    await expect(page.getByLabel("Draft message")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Approve draft" }),
    ).toHaveCount(0);
  });

  test("never writes server text as HTML", async ({ page }) => {
    const hostile = makeCase(1, {
      draft: {
        version: 2,
        source: "mentor",
        author: "<img src=x onerror=window.__pwned=1>",
        created_on: "2026-03-02",
        message: "<script>window.__pwned = 1</script>",
      },
      state: "monitoring",
    });
    await new FakeApi([hostile]).install(page);
    await signIn(page, "mentor");
    await page.goto("/cases/1");
    await expect(
      page.getByText("<script>window.__pwned = 1</script>"),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => (window as unknown as { __pwned?: number }).__pwned,
      ),
    ).toBeUndefined();
  });
});

test.describe("other roles", () => {
  test("staff can act but cannot approve or edit the draft", async ({
    page,
  }) => {
    await new FakeApi([makeCase(1)], "staff").install(page);
    await signIn(page, "staff", "hod");
    await page.goto("/cases/1");
    await expect(page.getByRole("button", { name: "Dismiss" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Approve draft" }),
    ).toHaveCount(0);
    await expect(page.getByLabel("Draft message")).toHaveCount(0);
    await expect(page.getByText("Hi, how are you getting on?")).toBeVisible();
  });

  test("admin can read a case but sees no draft, reasons or actions", async ({
    page,
  }) => {
    await new FakeApi([makeCase(1)], "admin").install(page);
    await signIn(page, "admin", "root");
    await page.goto("/cases/1");
    await expect(
      page.getByRole("heading", { name: /Student 10/ }),
    ).toBeVisible();
    await expect(
      page.getByText("Administrators can read cases but not act on them."),
    ).toBeVisible();
    await expect(page.getByText("Attendance is 40% so far")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: /Approve|Dismiss/ }),
    ).toHaveCount(0);
  });

  test("faculty are offered no case screens and the app never asks the API for cases", async ({
    page,
  }) => {
    const api = new FakeApi([makeCase(1)], "mentor");
    await api.install(page);
    await signIn(page, "faculty", "f1");
    await page.goto("/");
    await expect(
      page.getByText("There are no screens for your role yet."),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Caseload" })).toHaveCount(0);
    for (const path of ["/caseload", "/cases/1"]) {
      await page.goto(path);
      await expect(
        page.getByText("This screen is not available for your role."),
      ).toBeVisible();
    }
    expect(api.requests).toHaveLength(0);
  });
});

test.describe("small screens", () => {
  test.use({ viewport: { width: 375, height: 667 } });

  for (const path of ["/caseload", "/cases/1"]) {
    test(`${path} does not scroll sideways on a phone`, async ({ page }) => {
      await new FakeApi([
        makeCase(1, {
          draft: { ...makeCase(1).draft!, message: "word ".repeat(150).trim() },
        }),
      ]).install(page);
      await signIn(page, "mentor");
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText(/Student 10/).first()).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});
