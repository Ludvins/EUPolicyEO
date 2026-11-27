import { defineConfig } from "@playwright/test";
const base = process.env.PAGES_BASE || "/EUPolicyEO/";
const port = Number(process.env.E2E_PORT || 4173);
const origin = "http://127.0.0.1:" + port;
export default defineConfig({
  testDir: "./tests/e2e",
  workers: 1,
  timeout: 120_000,
  use: { browserName: "chromium", channel: process.env.E2E_CHANNEL || undefined,
    baseURL: origin + base },
  webServer: { command: "npm run preview -- --host 127.0.0.1 --port " + port + " --strictPort",
    url: origin + base, reuseExistingServer: false },
});
