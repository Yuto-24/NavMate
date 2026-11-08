import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e", testMatch: ["dev-shared.spec.ts"], workers: 1,
  metadata: { applicationMode: "local" },
  timeout: 120_000, expect: { timeout: 30_000 }, reporter: "line",
  outputDir: "/tmp/navmate-dev-shared-results",
  use: { ...devices["Desktop Chrome"], baseURL: process.env.AUTONAVLOG_LOCAL_URL ?? "http://127.0.0.1:4175",
    trace: "retain-on-failure" },
  webServer: process.env.AUTONAVLOG_LOCAL_URL ? undefined : {
    command: "python3 ../tests/integration/serve_dev_shared.py",
    url: "http://127.0.0.1:4175/", reuseExistingServer: false,
  },
});
