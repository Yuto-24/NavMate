import { defineConfig } from "@playwright/test";

// Adapter and architecture tests require no browser, Docker, or application server.
export default defineConfig({
  testDir: "./e2e", testMatch: ["sea-display.spec.ts", "forms.spec.ts", "display-rounding.spec.ts", "fuel-plan-display.spec.ts", "gsi-airspace-unit.spec.ts", "terrain-unit.spec.ts", "import-route-draft-unit.spec.ts", "branding-unit.spec.ts", "map-route-unit.spec.ts", "sync-unit.spec.ts", "sync-payload-unit.spec.ts", "taf-unit.spec.ts", "application.spec.ts", "forecast-backup-unit.spec.ts", "auth-unit.spec.ts", "persistence-unit.spec.ts", "platform-unit.spec.ts", "local-weather-unit.spec.ts", "information-state.spec.ts", "vor-unit.spec.ts"], workers: 1, outputDir: "/tmp/autonavlog-application-tests", reporter: "line",
});
