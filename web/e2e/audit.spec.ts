import { expect, test } from "@playwright/test";

import type { AuditEntry } from "../lib/types";
import { FakeApi, appAlert, makeCase, signIn } from "./fake-api";

function entry(seq: number, overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    seq,
    at: "2026-03-02T01:00:00+00:00",
    actor_kind: "system",
    actor_id: null,
    action: "nightly.run",
    subject_kind: "pipeline",
    subject_ref: "2026-03-02",
    hash_prefix: `abc${String(seq).padStart(3, "0")}def012`,
    ...overrides,
  };
}

function admin(log: AuditEntry[] = []) {
  const api = new FakeApi([makeCase(1)], "admin");
  api.auditLog = log;
  return api;
}

test.describe("audit log", () => {
  test("lists entries newest first without any detail", async ({ page }) => {
    const api = admin([
      entry(1),
      entry(2, {
        action: "case.reassigned",
        actor_kind: "admin",
        actor_id: "root",
        subject_kind: "case",
        subject_ref: "case-7",
      }),
    ]);
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/audit");

    const rows = page.locator("tbody tr");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText("case.reassigned");
    await expect(rows.nth(0)).toContainText("admin · root");
    await expect(rows.nth(0)).toContainText("case · case-7");
    await expect(rows.nth(0)).toContainText("abc002def012");
    await expect(rows.nth(1)).toContainText("nightly.run");
    await expect(page.getByText("2 entries, newest first")).toBeVisible();
  });

  test("says so when the log is empty", async ({ page }) => {
    await admin().install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/audit");
    await expect(page.getByText("No entries.")).toBeVisible();
  });

  test("filters by action and goes back to the first page", async ({
    page,
  }) => {
    const api = admin([
      entry(1),
      entry(2, { action: "nightly.halted" }),
      entry(3),
    ]);
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/audit");
    await expect(page.locator("tbody tr")).toHaveCount(3);

    await page
      .getByLabel("Show only this action (exact)")
      .fill(" nightly.halted ");
    await page.getByRole("button", { name: "Filter" }).click();
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await expect(page.locator("tbody tr")).toContainText("nightly.halted");
    const call = api.calls("GET", "/api/admin/audit").at(-1);
    expect(call?.query).toContain("action=nightly.halted");
    expect(call?.query).toContain("offset=0");
  });

  test("pages through more than fifty entries", async ({ page }) => {
    const log = Array.from({ length: 60 }, (_, i) => entry(i + 1));
    await admin(log).install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/audit");

    await expect(page.locator("tbody tr")).toHaveCount(50);
    await expect(page.locator("tbody tr").first()).toContainText("60");
    await expect(
      page.getByRole("button", { name: "Previous", exact: true }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.locator("tbody tr")).toHaveCount(10);
    await expect(
      page.getByRole("button", { name: "Next", exact: true }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "Previous", exact: true }).click();
    await expect(page.locator("tbody tr")).toHaveCount(50);
  });

  test("hostile text in a field is shown as text", async ({ page }) => {
    const api = admin([
      entry(1, {
        actor_id: "<img src=x onerror=alert(1)>",
        subject_ref: "<b>x</b>",
      }),
    ]);
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/audit");
    await expect(page.getByText("<b>x</b>", { exact: false })).toBeVisible();
    await expect(page.locator("main img")).toHaveCount(0);
  });

  test("shows the server's error", async ({ page }) => {
    const api = admin([entry(1)]);
    await api.install(page);
    await signIn(page, "admin", "root");
    api.failNext(500, null, 2);
    await page.goto("/admin/audit");
    await expect(appAlert(page)).toContainText("Could not load the log");
  });

  test("an intact chain reports the anchor to keep", async ({ page }) => {
    const api = admin([entry(1)]);
    api.auditCheck = {
      ok: true,
      checked: 1,
      first_bad_seq: null,
      problem: null,
      anchor: "1:" + "a".repeat(64),
    };
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/audit");

    await page.getByRole("button", { name: "Check now" }).click();
    await expect(page.getByRole("status")).toContainText(
      "Intact: 1 entry checked",
    );
    await expect(page.getByRole("status")).toContainText("1:" + "a".repeat(64));
    expect(api.calls("GET", "/api/admin/audit/verify")[0].query).toBe("");
  });

  test("a saved anchor is sent with the check", async ({ page }) => {
    const api = admin([entry(1)]);
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/audit");

    await page.getByLabel("Saved anchor (optional)").fill("  1:abc  ");
    await page.getByRole("button", { name: "Check now" }).click();
    await expect(page.getByRole("status")).toBeVisible();
    expect(api.calls("GET", "/api/admin/audit/verify")[0].query).toBe(
      "anchor=1%3Aabc",
    );
  });

  test("a broken chain is shown as a problem, not as success", async ({
    page,
  }) => {
    const api = admin([entry(1), entry(2)]);
    api.auditCheck = {
      ok: false,
      checked: 2,
      first_bad_seq: 2,
      problem: "hash does not match",
      anchor: null,
    };
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/audit");

    await page.getByRole("button", { name: "Check now" }).click();
    await expect(appAlert(page)).toContainText(
      "The log does not check out (first problem at entry 2): hash does not match.",
    );
    await expect(page.getByRole("status")).toHaveCount(0);
  });

  test("a refused check shows the server's answer", async ({ page }) => {
    const api = admin([entry(1)]);
    await api.install(page);
    await signIn(page, "admin", "root");
    await page.goto("/admin/audit");
    await expect(page.locator("tbody tr")).toHaveCount(1); // the list has loaded
    api.failNext(422, "anchor must look like SEQ:HASH");
    await page.getByLabel("Saved anchor (optional)").fill("nonsense");
    await page.getByRole("button", { name: "Check now" }).click();
    await expect(appAlert(page)).toHaveText("anchor must look like SEQ:HASH");
  });

  for (const role of ["mentor", "staff", "faculty"] as const) {
    test(`${role} gets no Audit link and makes no request`, async ({
      page,
    }) => {
      const api = new FakeApi([], role);
      await api.install(page);
      await signIn(page, role);
      await page.goto("/admin/audit");
      await expect(appAlert(page)).toHaveText(
        "This screen is not available for your role.",
      );
      await expect(page.getByRole("link", { name: "Audit" })).toHaveCount(0);
      expect(
        api.requests.filter((r) => r.path.includes("/audit")),
      ).toHaveLength(0);
    });
  }

  test("admin reaches it from the menu and it fits a phone", async ({
    page,
  }) => {
    await admin([entry(1)]).install(page);
    await signIn(page, "admin", "root");
    await page.setViewportSize({ width: 375, height: 700 });
    await page.goto("/caseload");
    await page.getByRole("link", { name: "Audit" }).click();
    await expect(
      page.getByRole("heading", { name: "Audit log" }),
    ).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(1);
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
