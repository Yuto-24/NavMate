import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "./helpers/localArtifact";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";
import { expectPlanningLayout } from "./helpers/planningLayout";

async function calculate(page: Page) {
  await page.goto("/");
  await enterImportWorkflow(page);
  await page.locator('input[type="file"]').setInputFiles(resolve("../tests/fixtures/issue_43_golden.kml"));
  await confirmImportedDraft(page);
  await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.getByLabel("地上風向 ° FROM").fill("360");
  await page.getByLabel("地上風速 kt").fill("15");
  await page.getByLabel("5,000 ft風向 ° FROM").fill("270");
  await page.getByLabel("5,000 ft風速 kt").fill("30");
  await page.getByLabel("ETD JST", { exact: true }).fill("09:00");
  for (const [name, altitude] of [["RJFM", "6500"], ["米ノ津", "7500"], ["玉名", "6500"]]) {
    await page.getByLabel(`${name}出発Legの計画高度`, { exact: true }).fill(altitude!);
  }
  await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
  await expect(page.locator(".nav-log-table")).toBeVisible();
}

test("#477 clean PNG includes both tables, selected VORs and current modes without controls", async ({ page }, info) => {
  await page.addInitScript(() => {
    const root = window as any;
    root.pngText = [];
    const draw = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (...args) {
      if (document.querySelector(".nav-log-png-paper")) root.pngText.push(args[0]);
      return draw.apply(this, args);
    };
    const encode = HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob = function (callback, ...args) {
      const paper = document.querySelector(".nav-log-png-paper");
      if (paper) {
        root.pngSnapshot = {
          controls: paper.querySelectorAll("input, select, button").length,
          rows: Array.from(paper.querySelectorAll(".nav-log-table tr:not(.nav-leg-spacer-row)"), row =>
            Array.from(row.querySelectorAll("th, td"), cell => cell.textContent)),
          spacers: Array.from(paper.querySelectorAll(".nav-leg-spacer-row"), row => ({
            height: row.getBoundingClientRect().height, next: row.nextElementSibling?.className,
          })),
          parents: paper.querySelectorAll(".nav-leg-heading-row").length,
          emptyActuals: Array.from(paper.querySelectorAll(".manual-entry-cell"), cell => cell.textContent),
        };
        if (root.failPng) { callback(null); return; }
      }
      encode.call(this, callback, ...args);
    };
  });
  await calculate(page);
  const reciprocal = page.getByRole("checkbox", { name: "RAD反方位（180°）" });
  const rounding = page.getByRole("radio", { name: "四捨五入", exact: true });
  await expect(reciprocal).toBeChecked();
  await expect(rounding).toBeChecked();
  const otherValues = await page.locator(".nav-log-table td:not(.vor-reference-cell)").allTextContents();
  const reversed = await page.locator(".vor-reference-cell").allTextContents();
  await reciprocal.uncheck();
  const direct = await page.locator(".vor-reference-cell").allTextContents();
  expect(await page.locator(".nav-log-table td:not(.vor-reference-cell)").allTextContents()).toEqual(otherValues);
  for (let index = 0; index < direct.length; index++) {
    const [rad, distance] = direct[index].split(" / ");
    const [reverse, sameDistance] = reversed[index].split(" / ");
    expect(distance).toBe(sameDistance);
    if (/^\d{3}$/.test(rad)) expect(Number(reverse)).toBe((Number(rad) + 180) % 360 || 360);
    else expect(reverse).toBe(rad);
  }
  await reciprocal.check();
  await page.getByLabel("VOR基準局", { exact: true }).selectOption("AKE");
  for (let index = 0; index < 3; index++) await page.getByRole("button", { name: "VOR/DME列を追加" }).click();
  await page.getByLabel("VOR基準局", { exact: true }).selectOption("SUC");
  const output = page.getByRole("button", { name: "NAVLOG・Fuel TableをPNG保存" });
  await expect(output).toBeEnabled();
  for (const width of [1100, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expectPlanningLayout(page, width);
  }
  await page.locator(".nav-log-scroll").evaluate(el => { el.scrollLeft = el.scrollWidth; });
  const expectedCells = await page.locator(".nav-log-table").evaluate(table => {
    const empty = Array.from(table.querySelectorAll<HTMLElement>("thead th"))
      .flatMap((cell, index) => cell.dataset.pngText === "" ? [index] : []);
    return Array.from(table.querySelectorAll("tbody tr:not(.nav-leg-spacer-row)"), row =>
      Array.from(row.querySelectorAll<HTMLElement>("td"))
        .filter((_, index) => !empty.includes(index))
        .map(cell => cell.dataset.displayText ?? cell.textContent));
  });
  const downloadPromise = page.waitForEvent("download");
  await output.click();
  const download = await downloadPromise;
  const path = info.outputPath("NAVLOG.png");
  await download.saveAs(path);
  const bytes = readFileSync(path);
  expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  expect(bytes.readUInt32BE(16)).toBeGreaterThan(bytes.readUInt32BE(20));
  expect(bytes.readUInt32BE(16)).toBeLessThanOrEqual(4096);
  const snapshot = await page.evaluate(() => ({ snapshot: (window as any).pngSnapshot, text: (window as any).pngText }));
  expect(snapshot.snapshot.controls).toBe(0);
  expect(snapshot.snapshot.rows.slice(1)).toEqual(expectedCells);
  expect(snapshot.snapshot.rows[0]).toHaveLength(22); // 20 base columns + two selected VORs.
  expect(snapshot.snapshot.spacers).toHaveLength(snapshot.snapshot.parents - 1);
  expect(snapshot.snapshot.spacers.every((row: any) => row.height >= 20 && row.next.includes("nav-leg-heading-row"))).toBe(true);
  expect(snapshot.snapshot.emptyActuals.every((value: string) => value === "")).toBe(true);
  expect(snapshot.text.join(" ")).toContain("TIME / FUEL PLAN");
  expect(snapshot.text.join(" ")).toContain("四捨五入 / RAD 反方位");
  expect(snapshot.snapshot.rows[0].join(" ")).toContain("AKE AMAKUSA");
  expect(snapshot.snapshot.rows[0].join(" ")).toContain("SUC SHIMIZU");
  await expect(page.locator(".nav-log-png-paper")).toHaveCount(0);
  await expect(page.locator(".nav-log-table input").first()).toBeAttached();
  await info.attach("清書PNG", { path, contentType: "image/png" });

  // Encoding failure preserves the live table and makes retry possible.
  await page.evaluate(() => { (window as any).failPng = true; });
  await output.click();
  await expect(page.getByRole("status").filter({ hasText: "PNGを保存できませんでした" })).toBeVisible();
  await expect(output).toBeEnabled();
  await expect(reciprocal).toBeChecked();
  await expect(page.locator(".nav-log-png-paper")).toHaveCount(0);
  // Stress the renderer with a synthetic long table, without modifying saved work.
  await page.evaluate(() => {
    (window as any).failPng = false;
    const table = document.querySelector<HTMLTableElement>(".nav-log-table")!;
    const parent = table.querySelector(".nav-leg-heading-row")!;
    for (let index = 0; index < 120; index++) {
      const row = parent.cloneNode(true) as HTMLElement;
      const name = row.querySelector<HTMLElement>(".route-to-cell")!;
      name.dataset.displayText = `PNG-ROW-${index}`;
      name.textContent = name.dataset.displayText;
      table.tBodies[0].append(row);
    }
  });
  const longDownload = page.waitForEvent("download");
  await output.click();
  const longFile = await longDownload;
  const longPath = info.outputPath("NAVLOG-long.png");
  await longFile.saveAs(longPath);
  const longBytes = readFileSync(longPath);
  expect(longBytes.readUInt32BE(16)).toBeGreaterThan(longBytes.readUInt32BE(20));
  expect(longBytes.readUInt32BE(16)).toBeLessThanOrEqual(4096);
  const longSnapshot = await page.evaluate(() => (window as any).pngSnapshot);
  expect(longSnapshot.rows.at(-1).join(" ")).toContain("PNG-ROW-119");
  expect(longSnapshot.parents).toBe(snapshot.snapshot.parents + 120);
  expect(longSnapshot.spacers).toHaveLength(longSnapshot.parents - 1);
  const temperature = page.locator('.nav-log-table input[aria-label$="手動気温"]').first();
  await temperature.fill("100");
  await expect(output).toBeDisabled();
});
