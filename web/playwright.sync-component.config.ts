import { defineConfig } from "@playwright/test";
import sync from "./playwright.sync.config";

// Real browser/dialog behavior, without the SDK, emulator or Python calculator.
export default defineConfig(sync, {
  testMatch: "sync-component.spec.ts",
  outputDir: "/tmp/autonavlog-sync-component-browser",
});
