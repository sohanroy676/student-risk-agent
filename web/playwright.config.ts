import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;
const ci = !!process.env.CI;

// The tests stand in for the API at the network layer (see e2e/fake-api.ts), so only the web
// app runs. CI tests the production build; locally the dev server is reused if already running.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: ci,
  retries: ci ? 1 : 0,
  reporter: ci ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://localhost:${PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: ci
      ? `npm run build && npm run start -- --port ${PORT}`
      : `npm run dev -- --port ${PORT}`,
    url: `http://localhost:${PORT}/login`,
    reuseExistingServer: !ci,
    timeout: 240_000,
    env: { NEXT_PUBLIC_DEV_TOKEN_LOGIN: "true", API_URL: "http://localhost:9" },
  },
});
