import { expect, type Page } from "@playwright/test";

/** #416: map and controls form one workspace; NAV LOG remains below it. */
export async function expectPlanningLayout(page: Page, width: number) {
  const map = page.locator(".map-frame");
  const pane = page.locator(".planning-pane");
  await expect(map).toBeVisible();
  await expect(pane).toBeVisible();
  // Sample together: calculation may be smoothly scrolling to NAV LOG.
  const [m, p, r, n] = await page.evaluate(() =>
    [".map-frame", ".planning-pane", ".planning-pane .status-rail", ".nav-log-section"].map(selector => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const { x, y, width, height } = element.getBoundingClientRect();
      return { x, y, width, height };
    }),
  );
  if (!m || !p) throw new Error("Planning workspace is missing");
  for (const box of [m, p]) {
    expect(box.width).toBeGreaterThan(0);
    expect(box.height).toBeGreaterThan(0);
  }
  if (width <= 700) expect(p.y).toBeGreaterThanOrEqual(m.y + m.height - 1);
  else {
    expect(p.x).toBeGreaterThanOrEqual(m.x + m.width - 1);
    expect(Math.abs(p.y - m.y)).toBeLessThanOrEqual(1);
  }
  if (r) {
    expect(r.y).toBeGreaterThanOrEqual(p.y - 1);
    expect(r.y + r.height).toBeLessThanOrEqual(p.y + p.height + 1);
  }
  if (n) expect(n.y).toBeGreaterThanOrEqual(Math.max(m.y + m.height, p.y + p.height) - 1);
}
