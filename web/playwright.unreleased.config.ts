import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { buildHead } from "./scripts/unreleased-notes.mjs";
const head = buildHead(fileURLToPath(new URL("..", import.meta.url)));
const scenarios = ["ready", "empty", "unavailable", "production"];
export default defineConfig({
  testDir: "./e2e", testMatch: "unreleased-notes.spec.ts", workers: 1,
  timeout: 120_000, expect: { timeout: 30_000 }, reporter: "line",
  outputDir: "/tmp/navmate-543-browser/results",
  projects: scenarios.map((scenario, index) => ({ name: scenario,
    use: { ...devices["Desktop Chrome"], baseURL: `http://127.0.0.1:${5250 + index}` } })),
  webServer: scenarios.map((scenario, index) => ({
    command: `npx vite --host 127.0.0.1 --port ${5250 + index} --strictPort`,
    url: `http://127.0.0.1:${5250 + index}`, reuseExistingServer: false,
    env: { VITE_CALCULATION_MODE: "local", NAVMATE_LOCAL_DOCKER: scenario === "production" ? "0" : "1",
      NODE_OPTIONS: "--import=./e2e/fixtures/unreleased-github.mjs", UNRELEASED_SCENARIO: scenario,
      UNRELEASED_HEAD: head },
  })),
});
