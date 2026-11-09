import { defineConfig, devices } from "@playwright/test";

// Browser API contracts only; no application/Python runtime or UI is exercised.
export default defineConfig({
  testDir: "./e2e", testMatch: "terrain-browser.spec.ts", workers: 1,
  outputDir: "/tmp/navmate-terrain-tests", reporter: "line",
  use: { baseURL: "http://127.0.0.1:4193" },
  webServer: { command: "npx vite --host 127.0.0.1 --port 4193", url: "http://127.0.0.1:4193",
    reuseExistingServer: false },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
