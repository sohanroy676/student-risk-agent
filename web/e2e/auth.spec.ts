import { expect, test } from "@playwright/test";

import { FakeApi, appAlert, makeCase, signIn, tokenFor } from "./fake-api";

test("a mentor token signs in and lands on the caseload", async ({ page }) => {
  await new FakeApi([makeCase(1)]).install(page);
  await page.goto("/login");
  await page.getByLabel("Access token").fill(tokenFor("mentor"));
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/caseload$/);
  await expect(page.getByRole("heading", { name: "Caseload" })).toBeVisible();
  await expect(page.getByText("Mentor · m1")).toBeVisible();
});

test("tokens the app cannot use are refused with a reason", async ({
  page,
}) => {
  await page.goto("/login");
  const field = page.getByLabel("Access token");
  const submit = page.getByRole("button", { name: "Sign in" });

  await field.fill("not-a-token");
  await submit.click();
  await expect(appAlert(page)).toContainText("no role");

  await field.fill(tokenFor("student"));
  await submit.click();
  await expect(appAlert(page)).toContainText("no role");

  await field.fill(tokenFor("mentor", { exp: 1000 }));
  await submit.click();
  await expect(appAlert(page)).toContainText("expired");
  await expect(page).toHaveURL(/\/login$/);
});

test("without a sign-in every screen sends the visitor to the login page", async ({
  page,
}) => {
  const api = new FakeApi([makeCase(1)]);
  await api.install(page);
  for (const path of ["/", "/caseload", "/cases/1"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login$/);
  }
  expect(api.requests).toHaveLength(0);
});

test("an expired stored token counts as signed out", async ({ page }) => {
  await page.addInitScript(
    (value) => window.sessionStorage.setItem("sra.token", value),
    tokenFor("mentor", { exp: 1000 }),
  );
  await page.goto("/caseload");
  await expect(page).toHaveURL(/\/login$/);
});

test("a 401 from the API signs the user out", async ({ page }) => {
  const api = new FakeApi([makeCase(1)]);
  await api.install(page);
  await signIn(page, "mentor");
  api.failNext(401, "invalid or missing token");
  await page.goto("/caseload");
  await expect(page).toHaveURL(/\/login$/);
  expect(
    await page.evaluate(() => window.sessionStorage.getItem("sra.token")),
  ).toBeNull();
});

test("signing out clears the token", async ({ page }) => {
  await new FakeApi([makeCase(1)]).install(page);
  await signIn(page, "mentor");
  await page.goto("/caseload");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(
    await page.evaluate(() => window.sessionStorage.getItem("sra.token")),
  ).toBeNull();
});
