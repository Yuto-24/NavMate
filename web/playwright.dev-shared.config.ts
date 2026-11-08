import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e", testMatch: ["dev-shared.spec.ts", "dev-shared-firestore.spec.ts"], workers: 1,
  metadata: { applicationMode: "local" },
  timeout: 120_000, expect: { timeout: 30_000 }, reporter: "line",
  outputDir: "/tmp/navmate-dev-shared-results",
  use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:5179", trace: "retain-on-failure" },
  webServer: {
    command: "npx vite --host 127.0.0.1 --port 5179", url: "http://127.0.0.1:5179",
    reuseExistingServer: false,
    env: { VITE_CALCULATION_MODE: "local", VITE_DEV_SHARED_PROJECTS: "1",
      VITE_DEV_FIREBASE_PROJECT_ID: "navmate-6b281", VITE_DEV_FIREBASE_API_KEY: "emulator-only",
      VITE_DEV_FIREBASE_AUTH_DOMAIN: "navmate-6b281.firebaseapp.com", VITE_DEV_FIREBASE_APP_ID: "emulator-only" },
  },
});
