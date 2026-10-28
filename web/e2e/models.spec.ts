import { expect, test } from "@playwright/test";

import {
  FakeApi,
  appAlert,
  blockedBy,
  makeCase,
  makeRelease,
  signIn,
} from "./fake-api";

function registry(...releases: ReturnType<typeof makeRelease>[]) {
  const api = new FakeApi([makeCase(1)], "admin");
  api.releases = releases;
  return api;
}

test.describe("admin", () => {
  test("lists the releases with their verdicts and links to each", async ({
    page,
  }) => {
    const api = registry(
      makeRelease(3, { gate_now: blockedBy("gap_high:region") }),
      makeRelease(2, { in_production: true, gate_now: null }),
    );
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/models");

    const cards = page.getByRole("link", { name: /Release/ });
    await expect(cards).toHaveCount(2);
    await expect(cards.nth(0)).toContainText("Blocked (1)");
    await expect(cards.nth(1)).toContainText("In production");
    await expect(cards.nth(0)).toContainText("Week-4 AUC 0.740");
    await cards.nth(0).click();
    await expect(
      page.getByRole("heading", { name: /Release 3/ }),
    ).toBeVisible();
  });

  test("says so when nothing is registered", async ({ page }) => {
    await registry().install(page);
    await signIn(page, "admin", "root");
    await page.goto("/models");
    await expect(page.getByText("No model has been registered")).toBeVisible();
  });

  test("a release that passes the gate is promoted with one click", async ({
    page,
  }) => {
    const api = registry(
      makeRelease(2, { in_production: true, gate_now: null }),
      makeRelease(3),
    );
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/models/3");

    await page.getByRole("button", { name: "Promote to production" }).click();
    await expect(
      page.getByText("Release 3 is now in production."),
    ).toBeVisible();
    await expect(
      page.getByText("This release is in production."),
    ).toBeVisible();
    expect(api.calls("POST", "/api/admin/models/3/promote")[0].body).toEqual({
      reason: "",
      covers: [],
    });
  });

  test("a blocked release needs every block ticked and a reason before it can go live", async ({
    page,
  }) => {
    const api = registry(
      makeRelease(3, {
        metrics: {
          auc_week4: 0.74,
          ece: 0.02,
          recall_gaps: {
            gender: 0.03,
            region: 0.135,
            highest_education: 0.146,
          },
        },
        gate_now: blockedBy("gap_high:region", "gap_high:highest_education"),
      }),
    );
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/models/3");

    await expect(page.getByRole("cell", { name: "0.135" })).toBeVisible();
    await expect(page.getByText("Above the limit")).toHaveCount(2);
    await expect(page.getByText("Within the limit")).toHaveCount(1);

    const submit = page.getByRole("button", { name: "Promote with sign-off" });
    await expect(submit).toBeDisabled();
    await page.getByLabel(/gap_high:region/).check();
    await page
      .getByLabel("Reason for the sign-off")
      .fill("Pilot in one department only");
    await expect(submit).toBeDisabled(); // one block is still unaccepted
    await page.getByLabel(/gap_high:highest_education/).check();
    await expect(submit).toBeEnabled();
    await submit.click();

    await expect(
      page.getByText("Release 3 is now in production."),
    ).toBeVisible();
    expect(api.calls("POST", "/api/admin/models/3/promote")[0].body).toEqual({
      reason: "Pilot in one department only",
      covers: ["gap_high:region", "gap_high:highest_education"],
    });
  });

  test("a reason made only of spaces does not count", async ({ page }) => {
    await registry(makeRelease(3, { gate_now: blockedBy("ece_high") })).install(
      page,
    );
    await signIn(page, "admin", "root");
    await page.goto("/models/3");
    await page.getByLabel(/ece_high/).check();
    await page.getByLabel("Reason for the sign-off").fill("    ");
    await expect(
      page.getByRole("button", { name: "Promote with sign-off" }),
    ).toBeDisabled();
  });

  test("missing numbers cannot be signed off: there is no form at all", async ({
    page,
  }) => {
    await registry(
      makeRelease(3, {
        metrics: { auc_week4: 0.74, ece: 0.02, recall_gaps: { gender: null } },
        gate_now: {
          passed: false,
          blocks: [],
          hard_failures: ["unassessed:gender"],
          overridden: [],
          signed_off_by: null,
        },
      }),
    ).install(page);
    await signIn(page, "admin", "root");
    await page.goto("/models/3");

    await expect(page.getByText("no sign-off can change that")).toBeVisible();
    await expect(page.getByText("gender could not be assessed")).toBeVisible();
    await expect(page.getByText("Not assessed")).toBeVisible();
    await expect(page.getByLabel("Reason for the sign-off")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Promote/ })).toHaveCount(0);
  });

  test("shows what the gate still blocks when the server refuses", async ({
    page,
  }) => {
    const api = registry(makeRelease(3));
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/models/3");
    await expect(
      page.getByRole("heading", { name: /Release 3/ }),
    ).toBeVisible();
    api.failNext(409, { unresolved: ["auc_lower"], hard_failures: [] });
    await page.getByRole("button", { name: "Promote to production" }).click();
    await expect(appAlert(page)).toHaveText(
      "the gate still blocks this release: auc_lower",
    );
  });

  test("the model card is plain text, never HTML", async ({ page }) => {
    await registry(makeRelease(3)).install(page);
    await signIn(page, "admin", "root");
    await page.goto("/models/3");
    await page.getByText("Show the full card").click();
    await expect(page.getByText("<b>not html</b>")).toBeVisible();
    await expect(page.locator("pre b")).toHaveCount(0);
  });

  test("an unknown release reads as not found", async ({ page }) => {
    await registry(makeRelease(3)).install(page);
    await signIn(page, "admin", "root");
    await page.goto("/models/99");
    await expect(appAlert(page)).toContainText("release not found");
  });

  test("no model page shows a student-level number", async ({ page }) => {
    await registry(makeRelease(3)).install(page);
    await signIn(page, "admin", "root");
    await page.goto("/models/3");
    await expect(
      page.getByRole("heading", { name: /Release 3/ }),
    ).toBeVisible();
    await expect(page.locator("main")).not.toContainText(/Student \d/);
  });
});

test.describe("everyone else", () => {
  for (const role of ["mentor", "staff", "faculty"] as const) {
    test(`${role} is offered no Models link and sees no model data`, async ({
      page,
    }) => {
      const api = registry(makeRelease(3));
      await api.install(page);
      await signIn(page, role, "someone");
      await page.goto("/");
      await expect(page.getByRole("link", { name: "Models" })).toHaveCount(0);
      for (const path of ["/models", "/models/3"]) {
        await page.goto(path);
        await expect(
          page.getByText("This screen is not available for your role."),
        ).toBeVisible();
      }
      expect(api.calls("GET", "/api/admin/models")).toHaveLength(0);
    });
  }

  test("an admin sees the Models link", async ({ page }) => {
    await registry().install(page);
    await signIn(page, "admin", "root");
    await page.goto("/caseload");
    await expect(page.getByRole("link", { name: "Models" })).toBeVisible();
  });
});

test.describe("small screens", () => {
  test.use({ viewport: { width: 375, height: 667 } });

  for (const path of ["/models", "/models/3"]) {
    test(`${path} does not scroll sideways on a phone`, async ({ page }) => {
      await registry(
        makeRelease(3, {
          metrics: {
            auc_week4: 0.74,
            ece: 0.02,
            recall_gaps: {
              gender: 0.03,
              highest_education: 0.146,
              imd_band: 0.066,
            },
          },
          gate_now: blockedBy(
            "gap_high:highest_education",
            "gap_high:imd_band",
          ),
        }),
      ).install(page);
      await signIn(page, "admin", "root");
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText(/Release 3/).first()).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});
