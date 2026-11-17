import { defineConfig, devices } from "@playwright/test";

// These mixed tests retain UI assertions pending transfer from the Legacy harness.
// The caller supplies an explicitly isolated runtime; tests never start Compose.
export default defineConfig({
  testDir: "./e2e",
  testMatch: ["web.spec.ts", "rjfm-inbound.spec.ts", "information.spec.ts", "information-known-issues.spec.ts", "clipboard-import.spec.ts"],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: process.env.AUTONAVLOG_WEB_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
