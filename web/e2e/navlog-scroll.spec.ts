import { expectNavLogPaperGrid } from "./helpers/navLogGrid";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";
import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

async function expectNavLogAtViewportTop(page: Page) {
  const navLog = page.getByLabel("計算済みNAV LOG");
  const topLimit = await page.evaluate(() => window.innerHeight / 3);
  await expect(navLog).toBeFocused();
  await expect.poll(() => navLog.evaluate((element) => element.getBoundingClientRect().top))
    .toBeGreaterThanOrEqual(0);
  await expect.poll(() => navLog.evaluate((element) => element.getBoundingClientRect().top))
    .toBeLessThan(topLimit);
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
}

async function checkToastLayout(page: Page, width: number) {
  await page.setViewportSize({ width, height: 900 });
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  const geometry = await page.evaluate(() => {
    const box = (selector: string) => document.querySelector(selector)!.getBoundingClientRect().toJSON();
    const regions = [".input-rail", ".route-workspace", ".status-rail", ".nav-log-focus-target"];
    const before = regions.map(box);
    const toast = document.querySelector<HTMLElement>(".calculation-toast-region")!;
    toast.hidden = true;
    const withoutToast = regions.map(box);
    toast.hidden = false;
    return { before, withoutToast, toast: box(".calculation-toast"), header: box(".app-header"),
      guidance: Array.from(document.querySelectorAll(".rjfm-inbound-guidance"), el => el.getBoundingClientRect().toJSON()) };
  });
  expect(geometry.before).toEqual(geometry.withoutToast);
  expect(geometry.toast.left).toBeGreaterThanOrEqual(0);
  expect(geometry.toast.right).toBeLessThanOrEqual(width);
  expect(geometry.toast.bottom).toBeLessThanOrEqual(900);
  expect(geometry.toast.top).toBeGreaterThan(geometry.header.bottom);
  const [input, route, readiness, navlog] = geometry.before;
  if (width <= 1240) {
    expect(route.top).toBeGreaterThanOrEqual(input.bottom - 1);
    expect(readiness.top).toBeGreaterThanOrEqual(route.bottom - 1);
    expect(navlog.top).toBeGreaterThanOrEqual(readiness.bottom - 1);
  } else {
    expect(input.right).toBeLessThanOrEqual(route.left + 1);
    expect(route.right).toBeLessThanOrEqual(readiness.left + 1);
    expect(navlog.top).toBeGreaterThanOrEqual(Math.max(input.bottom, route.bottom, readiness.bottom) - 1);
  }
  for (const guidance of geometry.guidance) expect(guidance.top).toBeGreaterThanOrEqual(navlog.bottom - 1);
  // The header stays usable, and the modal backdrop covers the toast rather than the reverse.
  await page.getByRole("button", { name: /^お知らせ/ }).click();
  await expect(page.getByRole("dialog", { name: "お知らせ", exact: true })).toBeVisible();
  expect(await page.locator(".calculation-toast").evaluate(el => {
    const r = el.getBoundingClientRect();
    return Boolean(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest(".modal-backdrop"));
  })).toBe(true);
  await page.getByRole("button", { name: "お知らせを閉じる" }).click();
  await expect(page.locator(".calculation-toast")).toBeVisible();
  await page.getByLabel("計算済みNAV LOG").scrollIntoViewIfNeeded();
  await page.getByRole("button", { name: "VOR/DME列を追加" }).click();
  await page.getByRole("button", { name: /VOR\/DME .*列目を削除/ }).first().click();
  await page.screenshot({ path: `/tmp/issue219-toast-${width}.png` });
}

test("first Local NAV LOG calculation and recalculation scroll to the result", async ({ page }) => {
  await page.clock.install();
  await page.addInitScript(() => {
    const original = Element.prototype.scrollIntoView;
    const originalPostMessage = Worker.prototype.postMessage;
    (window as any).navLogScrolls = 0;
    (window as any).navLogScrollsAtCalculationStart = -1;
    Worker.prototype.postMessage = function (message: any, ...args: any[]) {
      this.addEventListener("error", () => { (window as any).localWorkerFailed = true; }, { once: true });
      if (message?.type === "APPLY" && message.argumentList?.[0]?.value === "calculate") {
        (window as any).navLogScrollsAtCalculationStart = (window as any).navLogScrolls;
      }
      return (originalPostMessage as any).call(this, message, ...args);
    };
    Element.prototype.scrollIntoView = function (...args) {
      if (this.getAttribute("aria-label") === "計算済みNAV LOG") {
        (window as any).navLogScrolls += 1;
      }
      return original.apply(this, args);
    };
  });
  await page.goto("/");
  await expect(page).toHaveTitle("NavMate");
  await enterImportWorkflow(page);
  await page.locator('input[type="file"]').setInputFiles(fileURLToPath(new URL("../../tests/fixtures/issue_43_golden.kml", import.meta.url)));
  await confirmImportedDraft(page);
  await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.getByLabel("地上風向 ° FROM").fill("360");
  await page.getByLabel("地上風速 kt").fill("15");
  await page.getByLabel("5,000 ft風向 ° FROM").fill("270");
  await page.getByLabel("5,000 ft風速 kt").fill("30");
  await page.getByLabel("ETD JST", { exact: true }).fill("09:00");
  for (const [name, altitude] of [["RJFM", "6500"], ["米ノ津", "7500"], ["玉名", "6500"]]) {
    await page.getByLabel(`${name}出発Legの計画高度`, { exact: true }).fill(altitude);
  }

  await expect(page.getByLabel("計算済みNAV LOG")).toHaveCount(0);
  const toast = page.locator(".calculation-toast");
  // Freeze before calculation so layout/assertion time on slower CI runners
  // cannot consume the toast's five-second lifetime.
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 200));
  await page.getByRole("button", { name: "NAV LOGを作る", exact: true }).click();
  await expect(toast).toHaveText("NAV LOGを計算しました。準備状況と各値を確認してください。");
  await page.clock.runFor(500); // Run the existing scroll-to-result frame.
  await expectNavLogAtViewportTop(page);
  expect(await page.evaluate(() => (window as any).navLogScrollsAtCalculationStart)).toBe(0);
  expect(await page.evaluate(() => (window as any).navLogScrolls)).toBe(1);
  await expectNavLogPaperGrid(page);
  const firstTable = await page.locator(".nav-log-table").innerText();
  await expect(page.locator(".calculation-toast-region")).toHaveAttribute("aria-live", "polite");
  const readiness = await page.locator(".status-rail").innerText();
  for (const width of [390, 1100, 1440]) await checkToastLayout(page, width);
  await page.clock.runFor(4_499);
  await expect(toast).toBeVisible();
  await page.clock.runFor(1);
  await expect(toast).toHaveCount(0);
  await expect(page.locator(".nav-log-table")).toHaveText(firstTable, { useInnerText: true });
  await expect(page.locator(".status-rail")).toHaveText(readiness, { useInnerText: true });
  await page.clock.resume();

  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.getByLabel("計算済みNAV LOG").evaluate((element) => element.getBoundingClientRect().top))
    .toBeGreaterThan(await page.evaluate(() => window.innerHeight / 3));
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 200));
  await page.getByRole("button", { name: "NAV LOGを再計算", exact: true }).click();
  await expect(toast).toBeVisible();
  await page.clock.runFor(500);
  await expectNavLogAtViewportTop(page);
  expect(await page.evaluate(() => (window as any).navLogScrollsAtCalculationStart)).toBe(1);
  expect(await page.evaluate(() => (window as any).navLogScrolls)).toBe(2);
  await expect(page.locator(".nav-log-table")).toHaveText(firstTable, { useInnerText: true });
  await expectNavLogPaperGrid(page);

  // A new successful calculation gets a fresh five seconds even if the old toast was still open.
  await page.clock.runFor(3_000);
  await expect(toast).toBeVisible();
  await page.getByRole("button", { name: "NAV LOGを再計算", exact: true }).click();
  await expect(toast).toBeVisible();
  await page.clock.runFor(2_000);
  await expectNavLogAtViewportTop(page);
  await expect(toast).toBeVisible();
  await toast.getByRole("button", { name: "メッセージを閉じる" }).click();
  await expect(toast).toHaveCount(0);
  await page.clock.runFor(5_000);
  await expect(page.locator(".nav-log-table")).toHaveText(firstTable, { useInnerText: true });
  await page.clock.resume();

  // Exercise Issue #276 against the real Local result in the hosted browser job.
  for (let index = 0; index < 5; index += 1) {
    await page.getByRole("button", { name: "VOR/DME列を追加" }).click();
  }
  const scroll = page.locator(".nav-log-scroll");
  for (const width of [390, 1100, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const left of [0, 420]) {
      await scroll.evaluate((element, left) => { element.scrollLeft = left; }, left);
      await expectNavLogPaperGrid(page);
    }
  }
  await page.emulateMedia({ media: "print" });
  await expectNavLogPaperGrid(page);
  await page.emulateMedia({ media: "screen" });
  const removeColumns = page.getByRole("button", { name: /VOR\/DME .*列目を削除/ });
  while (await removeColumns.count()) await removeColumns.first().click();
  await expectNavLogPaperGrid(page);
  // Other successes and calculation failures retain the existing persistent message bar.
  await page.getByRole("button", { name: "保存", exact: true }).click();
  const saved = page.getByRole("status").filter({ hasText: "プロジェクトを保存しました。" });
  await expect(saved).toBeVisible();
  await page.clock.fastForward(6_000);
  await expect(saved).toBeVisible();
  await expect(toast).toHaveCount(0);
  const worker = page.workers()[0]!;
  await page.evaluate(() => { (window as any).localWorkerFailed = false; });
  await worker.evaluate(() => { setTimeout(() => { throw new Error("Test Local Worker failure"); }, 0); });
  await page.waitForFunction(() => (window as any).localWorkerFailed);
  await page.getByRole("button", { name: "NAV LOGを再計算", exact: true }).click();
  const failure = page.getByRole("alert").filter({ hasText: "自動保存できませんでした" });
  await expect(failure).toBeVisible();
  await page.clock.fastForward(6_000);
  await expect(failure).toBeVisible();
  await expect(toast).toHaveCount(0);
  await expect(page.locator(".nav-log-table")).toHaveText(firstTable, { useInnerText: true });
});
