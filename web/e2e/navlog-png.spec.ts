import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createInflate } from "node:zlib";
import { Readable } from "node:stream";
import { test } from "./helpers/localArtifact";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";
import { expectPlanningLayout } from "./helpers/planningLayout";

// Decode the actual PNG stream, retaining only sampled scanlines for large images.
async function readPixels(bytes: Buffer, rows: number[]) {
  const width = bytes.readUInt32BE(16), height = bytes.readUInt32BE(20);
  const chunks: Buffer[] = [];
  for (let offset = 8; offset < bytes.length;) {
    const size = bytes.readUInt32BE(offset);
    if (bytes.toString("ascii", offset + 4, offset + 8) === "IDAT") {
      chunks.push(bytes.subarray(offset + 8, offset + 8 + size));
    }
    offset += size + 12;
  }
  const selected = new Map<number, Buffer>();
  let pending = Buffer.alloc(0), y = 0;
  const stride = width * 4 + 1;
  for await (const chunk of Readable.from(chunks).pipe(createInflate())) {
    pending = Buffer.concat([pending, chunk]);
    while (pending.length >= stride) {
      expect(pending[0]).toBe(0);
      if (rows.includes(y)) selected.set(y, Buffer.from(pending.subarray(1, stride)));
      pending = pending.subarray(stride);
      y++;
    }
  }
  expect(y).toBe(height);
  expect(pending.length).toBe(0);
  return (x: number, y: number) => Array.from(selected.get(y)!.subarray(x * 4, x * 4 + 3));
}

async function calculate(page: Page) {
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
      if (document.querySelector(".nav-log-png-paper")) {
        root.pngText.push(args[0]);
        root.pngScales ??= [];
        root.pngScales.push(this.getTransform().a);
      }
      return draw.apply(this, args);
    };
    const read = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function (...args) {
      const paper = document.querySelector(".nav-log-png-paper");
      if (paper) {
        if (root.failPng) throw new Error("Injected PNG failure");
        root.pngTiles ??= [];
        root.pngTiles.push([this.canvas.width, this.canvas.height]);
        if (root.pngPaper !== paper) {
          root.pngPaper = paper;
          const bounds = paper.getBoundingClientRect();
          const box = (selector: string) => {
            const cell = paper.querySelector(selector)!;
            const rect = cell.getBoundingClientRect();
            return { x: rect.left - bounds.left, y: rect.top - bounds.top,
              width: rect.width, height: rect.height };
          };
          root.pngSnapshot = {
            width: bounds.width, height: bounds.height,
            tableWidth: box(".nav-log-table").width,
            windWidth: box(".nav-log-table thead th:nth-last-child(11)").width,
            fuelWidth: box(".fuel-plan-table").width,
            fuelRowHeight: box(".fuel-extra-row").height,
            cellPadding: getComputedStyle(paper.querySelector(".route-from-cell")!).padding,
            vorLines: Array.from(paper.querySelectorAll(".vor-reference-header"), cell => cell.querySelectorAll("br").length),
            pairEnds: [8, 6, 2].map(column => Array.from(paper.querySelectorAll(`.nav-log-table tbody td:nth-last-child(${column}) .nav-log-zone-value`), value => {
              const range = document.createRange(); range.selectNodeContents(value);
              return range.getBoundingClientRect().right - value.closest("td")!.getBoundingClientRect().left;
            })),
            thin: box(".nav-log-table tbody tr:first-child .route-from-cell"),
            thick: box(".nav-log-table tbody tr:first-child .route-to-cell"),
            gray: box(".fuel-plan-table .fuel-gray"),
            double: box(".fuel-extra-row td:first-child"),
            last: box(".nav-log-table tbody tr:last-child .route-to-cell"),
            controls: paper.querySelectorAll("input, select, button").length,
            rows: Array.from(paper.querySelectorAll(".nav-log-table tr:not(.nav-leg-spacer-row)"), row =>
              Array.from(row.querySelectorAll("th, td"), cell => cell.textContent)),
            spacers: Array.from(paper.querySelectorAll(".nav-leg-spacer-row"), row => ({
              height: row.getBoundingClientRect().height, next: row.nextElementSibling?.className,
            })),
            parents: paper.querySelectorAll(".nav-leg-heading-row").length,
            emptyActuals: Array.from(paper.querySelectorAll(".manual-entry-cell"), cell => cell.textContent),
          };
        }
      }
      return read.apply(this, args);
    };
  });
  await calculate(page);
  const boundaries = page.locator(".nav-leg-detail-row").filter({ has: page.locator('.route-to-cell').filter({ hasText: /^(RCA|EOC)$/ }) });
  await expect(boundaries).toHaveCount(2);
  for (const cell of await boundaries.locator(".vor-reference-cell").all()) await expect(cell).toBeEmpty();
  await expect(page.locator(".nav-leg-heading-row .vor-reference-cell").first()).not.toBeEmpty();
  const reciprocal = page.getByRole("checkbox", { name: "RAD反方位（180°）" });
  const rounding = page.getByRole("radio", { name: "四捨五入", exact: true });
  await expect(reciprocal).toBeChecked();
  await expect(rounding).toBeChecked();
  const checkNumericPresentation = async () => {
    for (const column of [8, 6, 2]) {
      const values = page.locator(`.nav-log-table tbody td:nth-last-child(${column}) .nav-log-zone-value`);
      const ends = await values.evaluateAll(elements => elements.map(value => {
        const range = document.createRange(); range.selectNodeContents(value);
        return range.getBoundingClientRect().right - value.closest("td")!.getBoundingClientRect().left;
      }));
      expect(ends.length).toBeGreaterThan(4);
      expect(Math.max(...ends) - Math.min(...ends)).toBeLessThan(1);
      const texts = await page.locator(`.nav-log-table tbody td:nth-last-child(${column})`).allTextContents();
      if (column !== 2) {
        expect(texts.join(" ")).not.toMatch(/\.0(?:\s|$)/);
        expect(texts.some(text => /\.5/.test(text))).toBe(true);
      } else expect(texts.some(text => /\.0(?:\s|$)/.test(text))).toBe(true);
    }
  };
  await checkNumericPresentation();
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
  const normal = page.getByRole("radio", { name: "通常", exact: true });
  await normal.click();
  await expect(normal).toBeChecked();
  await expect(rounding).toBeEnabled();
  // Precision other than the trailing .0 still follows the selected mode.
  const normalDistances = await page.locator(".nav-log-table tbody td:nth-last-child(8)").allTextContents();
  expect(normalDistances.join(" ")).not.toMatch(/\.0(?:\s|$)/);
  await rounding.click();
  await expect(rounding).toBeChecked();
  await expect(rounding).toBeEnabled();
  await checkNumericPresentation();
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
  const decoded = await page.evaluate(async source => {
    const image = new Image();
    image.src = source;
    await image.decode();
    return [image.naturalWidth, image.naturalHeight];
  }, `data:image/png;base64,${bytes.toString("base64")}`);
  expect(decoded).toEqual([bytes.readUInt32BE(16), bytes.readUInt32BE(20)]);
  const snapshot = await page.evaluate(() => ({ snapshot: (window as any).pngSnapshot, text: (window as any).pngText }));
  const scale = bytes.readUInt32BE(20) / Math.ceil(snapshot.snapshot.height);
  expect(scale).toBeGreaterThanOrEqual(1);
  const { thin, thick, gray, double } = snapshot.snapshot;
  const thinY = Math.round((thin.y + 3) * scale), thickY = Math.round((thick.y + 3) * scale);
  const grayY = Math.round((gray.y + 3) * scale), doubleY = Math.round((double.y + double.height) * scale);
  const pixel = await readPixels(bytes, [thinY, thickY, grayY, doubleY - 3, doubleY - 2, doubleY - 1, doubleY, doubleY + 1, doubleY + 2, doubleY + 3]);
  const isGrid = (rgb: number[]) => rgb[0] < 210 && rgb[2] > rgb[0];
  const borderWidth = (cell: any, y: number) => {
    const x = Math.round((cell.x + cell.width) * scale);
    return Array.from({ length: 9 }, (_, index) => pixel(x - 6 + index, y)).filter(isGrid).length;
  };
  expect(borderWidth(thick, thickY)).toBeGreaterThan(borderWidth(thin, thinY));
  expect(pixel(Math.round((gray.x + 4) * scale), grayY)).toEqual([223, 228, 232]);
  const doubleX = Math.round((double.x + double.width / 2) * scale);
  const doubleLine = Array.from({ length: 7 }, (_, index) => isGrid(pixel(doubleX, doubleY - 3 + index)));
  expect(doubleLine.join(",")).toMatch(/true,false(?:,false)*,true/);
  expect(snapshot.snapshot.controls).toBe(0);
  expect(snapshot.snapshot.tableWidth).toBeLessThan(1500);
  expect(snapshot.snapshot.windWidth).toBeLessThan(80);
  expect(snapshot.snapshot.fuelWidth).toBeCloseTo(420, 0);
  expect(snapshot.snapshot.fuelRowHeight).toBeCloseTo(24, 0);
  expect(snapshot.snapshot.cellPadding).toBe("4px 6px");
  expect(snapshot.snapshot.vorLines).toEqual([1, 1]);
  for (const ends of snapshot.snapshot.pairEnds) {
    expect(ends.length).toBeGreaterThan(4);
    expect(Math.max(...ends) - Math.min(...ends)).toBeLessThan(1);
  }
  expect(snapshot.snapshot.rows.slice(1)).toEqual(expectedCells);
  const boundaryRows = snapshot.snapshot.rows.filter((row: string[]) => ["RCA", "EOC"].includes(row[3]));
  expect(boundaryRows).toHaveLength(2);
  expect(boundaryRows.every((row: string[]) => row[0] === "" && row[1] === "")).toBe(true);
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
      name.dataset.displayText = index === 0 ? "SPACE  \t  \n NAME" : `PNG-ROW-${index}`;
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
  const longSnapshot = await page.evaluate(() => (window as any).pngSnapshot);
  expect(longSnapshot.rows.at(-1).join(" ")).toContain("PNG-ROW-119");
  expect(longSnapshot.parents).toBe(snapshot.snapshot.parents + 120);
  expect(longSnapshot.spacers).toHaveLength(longSnapshot.parents - 1);
  expect(longBytes.readUInt32BE(20)).toBeGreaterThanOrEqual(Math.ceil(longSnapshot.height));
  expect(longSnapshot.last.width).toBeGreaterThan(snapshot.snapshot.last.width);
  const last = longSnapshot.last;
  const sampleY = Array.from({ length: Math.floor(last.height) - 6 }, (_, index) => Math.floor(last.y) + 3 + index);
  const lastPixel = await readPixels(longBytes, sampleY);
  expect(sampleY.some(y => Array.from({ length: Math.floor(last.width) - 12 }, (_, index) =>
    lastPixel(Math.floor(last.x) + 6 + index, y)).some(rgb => rgb.every(value => value < 80)))).toBe(true);
  const painted = await page.evaluate(() => ({ text: (window as any).pngText as string[], scales: (window as any).pngScales as number[] }));
  expect(painted.text).toContain("SPACE NAME");
  expect(painted.text.every(text => !/[\t\n\r\f]| {2}/.test(text))).toBe(true);
  expect(painted.scales.every(scale => scale >= 1)).toBe(true);
  expect(await page.evaluate(() => (window as any).pngTiles.every(([w, h]: number[]) => w <= 2048 && h <= 32))).toBe(true);
  const temperature = page.locator('.nav-log-table input[aria-label$="手動気温"]').first();
  await temperature.fill("100");
  await expect(output).toBeDisabled();
});
