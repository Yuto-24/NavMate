import { expect } from "@playwright/test";
import { resolve } from "node:path";
import { test, artifactSessionKey } from "./helpers/localArtifact";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";

for (const width of [1100, 1440]) {
  test(`#314 SEA automatic/unknown, reload, recalculation and workflow positions ${width}px`, async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    // Keep the first terrain request in flight to verify the pending state before it settles.
    let releaseTerrain!: () => void;
    const terrainGate = new Promise<void>(resolve => { releaseTerrain = resolve; });
    let heldFirstTile = false;
    await page.route("**/xyz/dem_png/**", async route => {
      if (!heldFirstTile) {
        heldFirstTile = true;
        await terrainGate;
      }
      await route.fulfill({ status: 404, body: "fixture missing" });
    });
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/");
    await enterImportWorkflow(page);
    await page.locator('input[type="file"]').setInputFiles(resolve("e2e/fixtures/terrain/sea-route.kml"));
    await confirmImportedDraft(page);
    await page.getByLabel("気象モード").selectOption("FTD");
    await page.getByLabel("地上風向 ° FROM").fill("360");
    await page.getByLabel("地上風速 kt").fill("15");
    await page.getByLabel("5,000 ft風向 ° FROM").fill("270");
    await page.getByLabel("5,000 ft風速 kt").fill("30");
    for (const input of await page.locator('input[aria-label$="出発Legの計画高度"]').all()) {
      await input.fill("2500"); await input.blur();
    }
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    const table = page.locator(".nav-log-table");
    await expect(table).toBeVisible();
    await expect(page.locator(".nav-log-sea-table")).toHaveCount(0);
    const headers = await table.locator("thead th").allTextContents();
    expect(headers.slice(headers.indexOf("TO"), headers.indexOf("TO") + 3)).toEqual(["TO", "SEAft MSL", "PAft"]);
    await expect(page.getByText("経路の左右3 NM", { exact: false })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "地形を再取得" })).toHaveClass(/secondary-button/);
    await expect(page.locator(".sea-panel details, .sea-panel input, .sea-panel code")).toHaveCount(0);
    await expect(page.getByText("地形点KML・DEMの取得状況と出典", { exact: true })).toHaveCount(0);
    const pending = table.locator(".nav-log-sea-cell").filter({ hasText: "取得中" }).first();
    await expect(pending).toBeVisible();
    await expect(pending.locator(".sea-loading-icon")).toBeVisible();
    await expect(page.locator(".sea-warning")).toHaveCount(0);
    releaseTerrain();
    // Acquisition has a 60 s budget; assert completion before the settled UI.
    await expect(page.getByRole("button", { name: "地形を再取得" })).toBeEnabled({ timeout: 90_000 });
    const first = table.locator('.nav-log-sea-cell[data-display-text="未確定"]').first();
    await expect(first).toHaveAttribute("data-display-text", "未確定");
    await expect(table.locator(".sea-loading-icon")).toHaveCount(0);
    await expect(first.locator("input")).toHaveCount(0);
    await expect(page.locator(".sea-warning").first()).toContainText("SEAは未確定です");
    const result = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!).working.outcome, artifactSessionKey);
    await page.reload();
    await enterImportWorkflow(page);
    await expect(first).toHaveAttribute("data-display-text", "未確定");
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    await expect(page.getByRole("button", { name: "地形を再取得" })).toBeEnabled({ timeout: 90_000 });
    const again = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!).working.outcome, artifactSessionKey);
    expect(again.summary).toEqual(result.summary);
    expect(again.fuel_plan).toEqual(result.fuel_plan);
    // Sample one frame, as in expectPlanningLayout: recalculation scrolls smoothly.
    const [map, pane, navlog, sea] = await page.evaluate(() =>
      [".map-frame", ".planning-pane", ".nav-log-scroll", ".sea-panel"].map(selector => {
        const { x, y, width, height } = document.querySelector(selector)!.getBoundingClientRect();
        return { x, y, width, height };
      }),
    );
    expect(map!.x + map!.width).toBeLessThanOrEqual(pane!.x + 2);
    expect(Math.abs(map!.y - pane!.y)).toBeLessThan(3);
    expect(navlog!.y).toBeGreaterThan(map!.y + map!.height);
    expect(sea!.y).toBeGreaterThan(navlog!.y);
    await expect(first).toHaveAttribute("data-display-text", "未確定");
    if (width === 1440) {
      // Seed two CPs on one physical Leg, then let the real Local engine project
      // and calculate them. Identical names must not merge the SEA intervals.
      await page.evaluate(key => {
        const session = JSON.parse(sessionStorage.getItem(key)!);
        const project = session.working.project;
        const section = project.sections[1];
        const start = project.route_nodes.find((node: any) => node.id === section.from_node_id);
        const end = project.route_nodes.find((node: any) => node.id === section.to_node_id);
        for (const fraction of [0.3, 0.7]) project.visual_references.push({
          id: crypto.randomUUID(), name: "SEA CP", role: "CHECK_POINT", source: "WEB_MANUAL",
          linked_section_id: section.id,
          latitude_deg: start.latitude_deg + fraction * (end.latitude_deg - start.latitude_deg),
          longitude_deg: start.longitude_deg + fraction * (end.longitude_deg - start.longitude_deg),
        });
        sessionStorage.setItem(key, JSON.stringify(session));
      }, artifactSessionKey);
      await page.reload();
      await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
      const cpRows = table.locator('tr[data-row-type="CALCULATION_ZONE"]').filter({ has: page.locator('.route-to-cell', { hasText: /^SEA CP$/ }) });
      await expect(cpRows).toHaveCount(2);
      const cpCells = cpRows.locator(".nav-log-sea-cell");
      await expect(cpCells).toHaveCount(2);
      await expect(cpCells.locator("input")).toHaveCount(0);
      await page.reload();
      await expect(cpCells).toHaveCount(2);
      await expect(page.getByRole("button", { name: "地形を再取得" })).toBeEnabled({ timeout: 90_000 });
      for (const cell of await cpCells.all()) await expect(cell).toHaveText("未確定");
      const state = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!).working, artifactSessionKey);
      expect(state.outcome.check_point_projections).toHaveLength(2);
      await expect(table.locator(".nav-log-sea-cell").filter({ hasText: /未確定|[0-9]/ }))
        .toHaveCount(state.project.sections.length + 2);
    }
    await page.locator(".nav-log-section").screenshot({ path: `/tmp/issue485-sea-${width}.png` });
    expect(errors).toEqual([]);
  });
}

for (const partial of [false, true]) {
test(`#314 #496 ${partial ? "partial" : "complete"} DEM, automatic values and retained diagnostics without detail UI`, async ({ page }) => {
  const display = partial ? "1100*" : "1100";
  // Allow initial readiness, reload recovery, and explicit DEM reacquisition to complete.
  test.setTimeout(300_000);
  const { deflateSync } = await import("node:zlib");
  // Numeric RGB fixture, 30.48 m = exactly 100 ft. PNG chunks have genuine CRCs.
  const crc = (data: Buffer) => {
    let c = 0xffffffff;
    for (const b of data) { c ^= b; for (let i = 0; i < 8; i++) c = (c >>> 1) ^ ((c & 1) ? 0xedb88320 : 0); }
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (name: string, data: Buffer) => {
    const type = Buffer.from(name), length = Buffer.alloc(4), sum = Buffer.alloc(4);
    length.writeUInt32BE(data.length); sum.writeUInt32BE(crc(Buffer.concat([type, data])));
    return Buffer.concat([length, type, data, sum]);
  };
  const header = Buffer.alloc(13); header.writeUInt32BE(256); header.writeUInt32BE(256, 4); header[8] = 8; header[9] = 2;
  const raw = Buffer.alloc(256 * 769);
  for (let y = 0; y < 256; y++) for (let x = 0; x < 256; x++) { raw[y * 769 + x * 3 + 2] = 11; raw[y * 769 + x * 3 + 3] = 232; }
  if (partial) for (let y = 0; y < 256; y++) for (let x = 0; x < 256; x += 2) {
    raw[y * 769 + x * 3 + 1] = 128;
    raw[y * 769 + x * 3 + 2] = 0;
    raw[y * 769 + x * 3 + 3] = 0;
  }
  const png = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
  await page.route("**/xyz/dem_png/**", route => route.fulfill({ contentType: "image/png", body: png }));
  await page.goto("/"); await enterImportWorkflow(page);
  await page.locator('input[type="file"]').setInputFiles(resolve("e2e/fixtures/terrain/sea-route.kml"));
  await confirmImportedDraft(page);
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.getByLabel("地上風向 ° FROM").fill("360"); await page.getByLabel("地上風速 kt").fill("15");
  await page.getByLabel("5,000 ft風向 ° FROM").fill("270"); await page.getByLabel("5,000 ft風速 kt").fill("30");
  for (const input of await page.locator('input[aria-label$="出発Legの計画高度"]').all()) {
    await input.fill("2500"); await input.blur();
  }
  await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
  const first = page.locator(".nav-log-sea-cell").filter({ hasText: /未確定|[0-9]/ }).first();
  await expect(first).toHaveAttribute("data-display-text", display, { timeout: 90_000 });
  await expect(first.locator("input")).toHaveCount(0);
  const saved = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!).working.project.metadata.sea, artifactSessionKey);
  const records = Object.values(saved.records) as { terrain: { complete: boolean; required: number; valid: number; provenance: { url: string; acquiredAt: string; sha256: string }[] } }[];
  const terrain = records[0]!.terrain;
  expect(terrain.complete).toBe(!partial);
  expect(terrain.required).toBeGreaterThan(0);
  if (partial) expect(terrain.valid).toBeLessThan(terrain.required);
  else expect(terrain.valid).toBe(terrain.required);
  expect(terrain.provenance.length).toBeGreaterThan(0);
  const { createHash } = await import("node:crypto");
  for (const source of terrain.provenance) {
    expect(source.url).toMatch(/^https:\/\/cyberjapandata\.gsi\.go\.jp\/xyz\/dem_png\/14\/\d+\/\d+\.png$/);
    expect(Number.isFinite(Date.parse(source.acquiredAt))).toBe(true);
    expect(source.sha256).toBe(createHash("sha256").update(png).digest("hex"));
    await expect(page.getByText(source.sha256, { exact: true })).toHaveCount(0);
  }
  await expect(page.locator(".sea-panel details, .sea-panel input, .sea-panel code")).toHaveCount(0);
  await page.reload();
  await enterImportWorkflow(page);
  await expect(first).toHaveAttribute("data-display-text", display);
  await expect(page.locator(".sea-caution")).toHaveCount(0);
  const restored = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!).working.project.metadata.sea, artifactSessionKey);
  expect(restored).toEqual(saved);
  // A saved number remains readable while an explicit reacquisition is in flight.
  let releaseRetry!: () => void;
  const retryGate = new Promise<void>(resolve => { releaseRetry = resolve; });
  let heldRetryTile = false;
  await page.route("**/xyz/dem_png/**", async route => {
    if (!heldRetryTile) {
      heldRetryTile = true;
      await retryGate;
    }
    await route.fallback();
  });
  await page.getByRole("button", { name: "地形を再取得" }).click();
  await expect(first.locator(".sea-loading-icon")).toBeVisible();
  await expect(first).toContainText(display);
  releaseRetry();
  await expect(page.getByRole("button", { name: "地形を再取得" })).toBeEnabled({ timeout: 90_000 });
  await expect(first.locator(".sea-loading-icon")).toHaveCount(0);
  await expect(first).toHaveAttribute("data-display-text", display);
  await expect(page.locator(".sea-caution")).toHaveCount(0);
  await expect(page.locator(".sea-reference-note")).toHaveCount(partial ? 1 : 0);
  if (partial) {
    for (const width of [1100, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      const [map, pane, navlog, note] = await page.evaluate(() =>
        [".map-frame", ".planning-pane", ".nav-log-scroll", ".sea-reference-note"].map(selector => {
          const { x, y, width, height } = document.querySelector(selector)!.getBoundingClientRect();
          return { x, y, width, height };
        }));
      expect(map!.x + map!.width).toBeLessThanOrEqual(pane!.x + 2);
      expect(Math.abs(map!.y - pane!.y)).toBeLessThan(3);
      expect(navlog!.y).toBeGreaterThan(map!.y + map!.height);
      expect(note!.y).toBeGreaterThanOrEqual(navlog!.y + navlog!.height);
      await page.locator(".nav-log-section").screenshot({ path: test.info().outputPath(`sea-reference-${width}.png`) });
    }
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "NAV LOG JSONをダウンロード" }).click();
    const file = await download;
    const { readFileSync } = await import("node:fs");
    const exported = JSON.parse(readFileSync((await file.path())!, "utf8"));
    expect(exported.sea.intervals.every((item: any) => item.reference && item.automatic_ft === 1100
      && item.terrain.evaluated && item.terrain.missing > 0)).toBe(true);
    await page.evaluate(() => {
      const texts: string[] = [];
      (window as any).__seaPngTexts = texts;
      const original = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function(text, x, y, maxWidth) {
        texts.push(text);
        return original.call(this, text, x, y, maxWidth!);
      };
    });
    const pngDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "PNG", exact: true }).click();
    expect((await pngDownload).suggestedFilename()).toMatch(/\.png$/);
    const texts = await page.evaluate(() => (window as any).__seaPngTexts as string[]);
    expect(texts).toContain("1100*");
    expect(texts.join("")).toContain("実際のSEAは表示値より高い可能性があります。");
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    await expect(first).toHaveAttribute("data-display-text", display);
  }
  // Restore an old manual override alongside complete high terrain: only the
  // automatic reference participates, while saved navigation values stay intact.
  await page.evaluate(key => {
    const session = JSON.parse(sessionStorage.getItem(key)!);
    for (const record of Object.values(session.working.project.metadata.sea.records) as any[]) {
      record.manual_ft = 1;
      record.terrain.maximum_m = 3048;
    }
    sessionStorage.setItem(key, JSON.stringify(session));
  }, artifactSessionKey);
  await page.reload();
  await enterImportWorkflow(page);
  await expect(first).toHaveAttribute("data-display-text", partial ? "11000*" : "11000");
  await expect(page.locator(".sea-caution").first()).toContainText("自動SEA（11000 ft）");
  const altitude = page.locator(".nav-log-table").getByRole("spinbutton", { name: /計画高度$/ }).first();
  await altitude.fill("3500");
  await expect(page.locator(".sea-caution")).toHaveCount(0);
  await altitude.blur();
  // NAV LOG edits invoke the existing automatic recalculation.
  await expect(page.locator(".sea-caution").first()).toBeVisible();
  await page.getByRole("button", { name: "地形を再取得" }).click();
  await expect(first).toHaveAttribute("data-display-text", display, { timeout: 90_000 });
  await expect(page.locator(".sea-caution")).toHaveCount(0);
});

}

test("#314 #485 final visual CP intervals retain SEA values without manual editors in NAV LOG", async ({ page }) => {
  await page.route("**/xyz/dem_png/**", route => route.fulfill({ status: 404, body: "fixture missing" }));
  await page.goto("/");
  await enterImportWorkflow(page);
  await page.locator('input[type="file"]').setInputFiles(resolve("e2e/fixtures/terrain/sea-route.kml"));
  await confirmImportedDraft(page);
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.getByLabel("地上風向 ° FROM").fill("360");
  await page.getByLabel("地上風速 kt").fill("15");
  await page.getByLabel("5,000 ft風向 ° FROM").fill("270");
  await page.getByLabel("5,000 ft風速 kt").fill("30");
  for (const input of await page.locator('input[aria-label$="出発Legの計画高度"]').all()) {
    await input.fill("2500"); await input.blur();
  }

  await page.evaluate(key => {
    const session = JSON.parse(sessionStorage.getItem(key)!);
    const project = session.working.project;
    const section = project.sections.at(-1);
    if (section.phase !== "VISUAL_ARRIVAL") throw new Error("Expected final visual leg");
    const start = project.route_nodes.find((node: any) => node.id === section.from_node_id);
    const end = project.route_nodes.find((node: any) => node.id === section.to_node_id);
    for (const [index, fraction] of [0.3, 0.7].entries()) project.visual_references.push({
      id: crypto.randomUUID(), name: `VISUAL CP ${index + 1}`, role: "CHECK_POINT", source: "WEB_MANUAL",
      linked_section_id: section.id,
      latitude_deg: start.latitude_deg + fraction * (end.latitude_deg - start.latitude_deg),
      longitude_deg: start.longitude_deg + fraction * (end.longitude_deg - start.longitude_deg),
    });
    sessionStorage.setItem(key, JSON.stringify(session));
  }, artifactSessionKey);
  await page.reload();
  await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
  const rows = page.locator(".nav-log-table tr[data-sea-only]");
  await expect(rows).toHaveCount(3);
  expect(await rows.locator(".route-to-cell").allTextContents()).toEqual(["VISUAL CP 1", "VISUAL CP 2", "RJFM"]);
  await expect(rows.locator("input")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "地形を再取得" })).toBeEnabled({ timeout: 90_000 });
  for (const cell of await rows.locator(".nav-log-sea-cell").all()) await expect(cell).toHaveText("未確定");
  expect(await rows.first().locator(".nav-log-sea-cell ~ td").allTextContents()).toEqual(Array(18).fill(""));
  await page.reload();
  await expect(rows).toHaveCount(3);
  await expect(page.getByRole("button", { name: "地形を再取得" })).toBeEnabled({ timeout: 90_000 });
  for (const cell of await rows.locator(".nav-log-sea-cell").all()) await expect(cell).toHaveText("未確定");
});
