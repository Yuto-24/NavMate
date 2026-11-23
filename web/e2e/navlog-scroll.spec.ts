import { expectPlanningLayout } from "./helpers/planningLayout";
import { openInformation } from "./helpers/header";
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
  await expectPlanningLayout(page, width);
  for (const guidance of geometry.guidance) expect(guidance.top).toBeGreaterThanOrEqual(navlog.bottom - 1);
  // The header stays usable, and the modal backdrop covers the toast rather than the reverse.
  await openInformation(page);
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
  await page.clock.install({ time: new Date("2026-09-11T00:00:00Z") });
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
  // The fixed target exceeds the test timeout, avoiding a clock-read round trip.
  await page.clock.pauseAt(new Date("2026-09-11T01:00:00Z"));
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
  // Keep timers paused through recalculation; only runFor advances toast time.
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await expect.poll(() => page.getByLabel("計算済みNAV LOG").evaluate((element) => element.getBoundingClientRect().top))
    .toBeGreaterThan(await page.evaluate(() => window.innerHeight / 3));
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
  // #443: presentation expires, but unresolved failures remain in the owning menu.
  await page.getByRole("button", { name: "保存", exact: true }).click();
  const saved = page.getByRole("status").filter({ hasText: "プロジェクトを保存しました。" });
  await expect(saved).toBeVisible();
  await page.clock.fastForward(6_000);
  await expect(saved).toHaveCount(0);
  await expect(toast).toHaveCount(0);
  const worker = page.workers()[0]!;
  await page.evaluate(() => { (window as any).localWorkerFailed = false; });
  await worker.evaluate(() => { setTimeout(() => { throw new Error("Test Local Worker failure"); }, 0); });
  await page.waitForFunction(() => (window as any).localWorkerFailed);
  await page.getByRole("button", { name: "NAV LOGを再計算", exact: true }).click();
  const failure = page.getByRole("alert").filter({ hasText: "自動保存できませんでした" });
  await expect(failure).toBeVisible();
  await page.clock.fastForward(6_000);
  await expect(failure).toHaveCount(0);
  await page.getByRole("button", { name: /^その他/ }).click();
  await expect(page.locator("#operation-messages")).toContainText("自動保存できませんでした");
  await page.getByRole("button", { name: /^その他/ }).click();
  await expect(toast).toHaveCount(0);
  await expect(page.locator(".nav-log-table")).toHaveText(firstTable, { useInnerText: true });
});

test("#412 rows align, names size independently, and sticky columns follow edits", async ({ page }, info) => {
  // Keep numeric snapshots independent of live DEM responses.
  await page.route("**/xyz/dem_png/**", route => route.fulfill({ status: 404, body: "fixture missing" }));
  await page.goto("/");
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
  await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
  const table = page.locator(".nav-log-table");
  await expect(table).toBeVisible();
  const terrainStatus = page.locator(".nav-log-footer-details > [role=status]");
  await expect(terrainStatus).toContainText("地形データを取得しています。");
  await expect(terrainStatus).toHaveCount(0, { timeout: 90_000 });
  await page.evaluate(() => document.fonts.ready);
  const widths = () => table.locator("thead .route-name-header")
    .evaluateAll(cells => cells.map(cell => cell.getBoundingClientRect().width));
  const originalWidths = await widths();
  expect(originalWidths.every(width => width < 110)).toBe(true);
  // The same one-VOR table previously needed 1,535px, before its outer border.
  expect((await table.boundingBox())!.width).toBeLessThan(1450);
  const numericValues = () => table.locator("td[data-display-text]:not(.route-name-cell)")
    .evaluateAll(cells => cells.map(cell => cell.getAttribute("data-display-text")));
  const before = await numericValues();
  const ordinaryRows = table.locator(".nav-leg-heading-row, .nav-leg-detail-row");
  const heights = await ordinaryRows.evaluateAll(rows => rows
    .filter(row => !Array.from(row.querySelectorAll("small")).some(el => el.textContent?.trim()))
    .map(row => row.getBoundingClientRect().height));
  expect(heights.length).toBeGreaterThan(5);
  expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(1);
  expect(Math.min(...heights)).toBeGreaterThanOrEqual(36);
  expect(await table.locator(".nav-leg-spacer-row").first().evaluate(el => el.getBoundingClientRect().height)).toBeLessThan(10);
  // Exercise longer paired numbers in the retained 90px columns without changing calculation data.
  expect(await table.locator(".nav-leg-heading-row .nav-log-pair").evaluateAll(pairs => pairs.every(pair => {
    const values = [pair.firstElementChild!, pair.lastElementChild!];
    const original = values.map(value => value.textContent);
    try {
      values.forEach(value => { value.textContent = "999.9"; });
      const cell = pair.closest("td")!.getBoundingClientRect();
      return values.every(value => {
        const range = document.createRange(); range.selectNodeContents(value);
        const text = range.getBoundingClientRect();
        return text.left >= cell.left && text.right <= cell.right;
      });
    } finally { values.forEach((value, index) => { value.textContent = original[index]; }); }
  }))).toBe(true);

  const checkLayout = async () => {
    const scroll = page.locator(".nav-log-scroll");
    for (const width of [390, 1100, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await expectPlanningLayout(page, width);
      for (const left of [0, 420, 10000]) {
        await scroll.evaluate((el, value) => { el.scrollLeft = value; }, left);
        await test.step(`NAV LOG grid at ${width}px, scroll ${left}px`, () => expectNavLogPaperGrid(page));
        const geometry = await table.locator("thead .route-name-header").evaluateAll(cells => {
          const [from, to] = cells.map(cell => cell.getBoundingClientRect());
          return { gap: to.left - from.right, left: from.left,
            offset: cells[0].closest(".nav-log-scroll")!.scrollLeft,
            preceding: Array.from(cells[0].parentElement!.querySelectorAll(".vor-reference-header"))
              .reduce((sum, cell) => sum + cell.getBoundingClientRect().width, 2),
            scrollLeft: cells[0].closest(".nav-log-scroll")!.getBoundingClientRect().left };
        });
        expect(Math.abs(geometry.gap)).toBeLessThan(1);
        expect(Math.abs(geometry.left - geometry.scrollLeft - Math.max(0, geometry.preceding - geometry.offset))).toBeLessThan(1);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    }
  };
  await checkLayout();
  // The same editable DOM node retains focus while errors/manual notes expand its row.
  const input = table.locator('input[aria-label$=" 手動気温"]').first();
  await input.fill("999");
  await expect(input).toBeFocused();
  await expect(input).toHaveAttribute("aria-invalid", "true");
  const inputRow = input.locator("xpath=ancestor::tr");
  await expect(inputRow.locator(".nav-log-field-error")).toBeVisible();
  expect((await inputRow.boundingBox())!.height).toBeGreaterThan(Math.max(...heights));
  await input.fill("12");
  await expect(input).toBeFocused();
  await expect(input).toHaveAttribute("aria-invalid", "false");
  await expect(inputRow.getByText("手入力", { exact: true })).toBeVisible();
  await input.fill("");
  await input.blur();
  await expect(page.locator(".nav-log-edit-status-saved")).toBeVisible();
  const direction = table.locator('input[aria-label$=" 手動風向"]').first();
  const wind = table.locator('input[aria-label$=" 手動風速"]').first();
  await direction.fill("360");
  await wind.fill("201");
  await expect(wind).toHaveAttribute("aria-invalid", "true");
  const windCell = wind.locator("xpath=ancestor::td");
  await expect(windCell.getByText("風向・風速を確認", { exact: true })).toBeVisible();
  await wind.fill("200");
  await expect(wind).toHaveAttribute("aria-invalid", "false");
  await expect(wind).toBeFocused();
  expect(await windCell.locator("input, small").evaluateAll(elements => elements.every(el => {
    const rect = el.getBoundingClientRect(), cell = el.closest("td")!.getBoundingClientRect();
    return rect.left >= cell.left && rect.right <= cell.right && rect.top >= cell.top && rect.bottom <= cell.bottom;
  }))).toBe(true);
  await wind.fill("");
  await direction.fill("");
  await wind.blur();
  await expect(page.locator(".nav-log-edit-status-saved")).toBeVisible();

  const rename = async (old: string, name: string) => {
    await page.getByRole("button", { name: `${old}を編集`, exact: true }).click();
    const field = page.getByRole("textbox", { name: `${old}の名称`, exact: true });
    await field.fill(name);
    await field.press("Enter");
    await expect(field).toHaveCount(0);
    await expect(table.locator(".route-to-cell").filter({ hasText: name }).first()).toHaveText(name);
    await page.evaluate(() => document.fonts.ready);
  };
  const medium = "玉名周辺の通過地点";
  await rename("玉名", medium);
  const mediumWidths = await widths();
  expect(mediumWidths[0]).toBeGreaterThan(originalWidths[0]);
  // Detail TO cells have an inset, so sharing a single max width is incorrect.
  expect(mediumWidths[1]).toBeGreaterThan(mediumWidths[0]);
  const long = "玉名付近のとても長い名称を持つ訓練経路上の通過地点ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  await rename(medium, long);
  expect((await widths()).every(width => width <= 160)).toBe(true);
  const longCell = table.locator(".nav-leg-heading-row .route-to-cell").filter({ hasText: long });
  expect((await longCell.boundingBox())!.height).toBeGreaterThan(Math.max(...heights));
  const contentFits = await longCell.evaluate(cell => {
    const range = document.createRange(); range.selectNodeContents(cell);
    const text = range.getBoundingClientRect(), box = cell.getBoundingClientRect();
    return text.left >= box.left && text.right <= box.right && text.top >= box.top && text.bottom <= box.bottom;
  });
  expect(contentFits).toBe(true);
  for (let index = 0; index < 2; index++) await page.getByRole("button", { name: "VOR/DME列を追加" }).click();
  await checkLayout();
  await longCell.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("long-names.png") });
  await page.getByRole("button", { name: /VOR\/DME .*列目を削除/ }).first().click();
  await page.getByRole("button", { name: /VOR\/DME .*列目を削除/ }).first().click();
  await rename(long, "玉名");
  expect(await widths()).toEqual(originalWidths);
  expect(await numericValues()).toEqual(before);
  await checkLayout();
  await table.screenshot({ path: info.outputPath("short-names.png") });
});
