import { expect } from "@playwright/test";
import { test } from "./helpers/localArtifact";

test("#422 startup displays one monotonic bar through real initialization before enabling the workspace", async ({ page }) => {
  await page.addInitScript(() => {
    const root = window as any;
    root.startupSamples = [];
    const observer = new MutationObserver(() => {
      const bars = [...document.querySelectorAll<HTMLProgressElement>(".loading-screen progress")];
      if (!bars.length) return;
      root.startupSamples.push({ count: bars.length, percent: bars[0].value,
        stage: document.querySelector('.loading-screen [role="status"]')?.textContent,
        workspace: !!document.querySelector(".map-frame") });
    });
    observer.observe(document, { childList: true, subtree: true, attributes: true, characterData: true });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible({ timeout: 120_000 });
  await expect(page.locator('input[type="file"]')).toBeEnabled();
  const samples = await page.evaluate(() => (window as any).startupSamples) as {
    count: number; percent: number; stage: string; workspace: boolean;
  }[];
  expect(samples.length).toBeGreaterThan(5);
  expect(samples.every(sample => sample.count === 1 && !sample.workspace)).toBe(true);
  expect(samples.map(sample => sample.percent)).toEqual(samples.map(sample => sample.percent).sort((a, b) => a - b));
  expect(samples.at(-1)?.percent).toBe(100);
  expect(new Set(samples.map(sample => sample.stage)).size).toBeGreaterThanOrEqual(5);
  await expect(page.locator(".loading-screen")).toHaveCount(0);
});

test("#422 failed runtime never reports startup complete or opens the workspace", async ({ page, context }) => {
  await context.route("https://cdn.jsdelivr.net/pyodide/**", route => route.abort());
  await page.goto("/");
  await expect(page.locator('[role="alert"] code')).toHaveText("APPLICATION_UNAVAILABLE", { timeout: 120_000 });
  const bar = page.getByRole("progressbar", { name: "起動の進み具合（目安）" });
  expect(Number(await bar.getAttribute("value"))).toBeLessThan(100);
  await expect(page.locator(".map-frame")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "起動を再試行", exact: true })).toBeEnabled();
});
