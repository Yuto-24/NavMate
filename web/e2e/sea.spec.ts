import { expect } from "@playwright/test";
import { resolve } from "node:path";
import { test, artifactSessionKey } from "./helpers/localArtifact";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";

for (const width of [1100, 1440]) {
  test(`#314 SEA unknown/manual, reload, recalculation and workflow positions ${width}px`, async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.route("**/xyz/dem_png/**", route => route.fulfill({ status: 404, body: "fixture missing" }));
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/");
    await enterImportWorkflow(page);
    await page.locator('input[type="file"]').setInputFiles(resolve("../tests/fixtures/issue_43_golden.kml"));
    await confirmImportedDraft(page);
    await page.getByLabel("気象モード").selectOption("FTD");
    await page.getByLabel("地上風向 ° FROM").fill("360");
    await page.getByLabel("地上風速 kt").fill("15");
    await page.getByLabel("5,000 ft風向 ° FROM").fill("270");
    await page.getByLabel("5,000 ft風速 kt").fill("30");
    for (const [name, altitude] of [["RJFM", "6500"], ["米ノ津", "7500"], ["玉名", "6500"]]) {
      const input = page.getByLabel(`${name}出発Legの計画高度`, { exact: true });
      await input.fill(altitude!); await input.blur();
    }
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    const table = page.locator(".nav-log-sea-table");
    await expect(table).toBeVisible();
    const first = table.locator("tbody tr").first();
    await expect(first).toContainText("未確定");
    const input = first.getByRole("spinbutton");
    await expect(input).toBeEnabled({ timeout: 90_000 });
    await input.fill("3500"); await input.blur();
    await expect(first).toContainText("手動");
    await expect(first).not.toContainText("地形データ不足");
    await expect(first).toContainText("自動値との照合は未実施");
    const result = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!).working.outcome, artifactSessionKey);
    await page.reload();
    await expect(input).toHaveValue("3500");
    await expect(first).toContainText("手動");
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    await expect(input).toBeEnabled({ timeout: 90_000 });
    await expect(input).toHaveValue("3500");
    const again = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!).working.outcome, artifactSessionKey);
    expect(again.summary).toEqual(result.summary);
    expect(again.fuel_plan).toEqual(result.fuel_plan);
    const [map, pane, navlog, sea] = await Promise.all([".map-frame", ".planning-pane", ".nav-log-scroll", ".sea-panel"]
      .map(selector => page.locator(selector).boundingBox()));
    expect(map!.x + map!.width).toBeLessThanOrEqual(pane!.x + 2);
    expect(Math.abs(map!.y - pane!.y)).toBeLessThan(3);
    expect(navlog!.y).toBeGreaterThan(map!.y + map!.height);
    expect(sea!.y).toBeGreaterThan(navlog!.y);
    await input.fill(""); await input.blur();
    await expect(first).toContainText("未確定");
    expect(errors).toEqual([]);
  });
}

test("#314 complete DEM, low manual warning, verified KML and failed import preservation", async ({ page }) => {
  test.setTimeout(180_000);
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
  const png = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
  await page.route("**/xyz/dem_png/**", route => route.fulfill({ contentType: "image/png", body: png }));
  await page.goto("/"); await enterImportWorkflow(page);
  await page.locator('input[type="file"]').setInputFiles(resolve("../tests/fixtures/issue_43_golden.kml"));
  await confirmImportedDraft(page);
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.getByLabel("地上風向 ° FROM").fill("360"); await page.getByLabel("地上風速 kt").fill("15");
  await page.getByLabel("5,000 ft風向 ° FROM").fill("270"); await page.getByLabel("5,000 ft風速 kt").fill("30");
  for (const [name, altitude] of [["RJFM", "6500"], ["米ノ津", "7500"], ["玉名", "6500"]]) {
    const input = page.getByLabel(`${name}出発Legの計画高度`, { exact: true });
    await input.fill(altitude!); await input.blur();
  }
  await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
  const first = page.locator(".nav-log-sea-table tbody tr").first();
  const input = first.getByRole("spinbutton");
  await expect(input).toBeEnabled({ timeout: 90_000 });
  await expect(input).toHaveAttribute("placeholder", "1100");
  await expect(first).toContainText("自動");
  await input.fill("1000"); await input.blur();
  await expect(first).toContainText("手動SEAが自動値（1100 ft）を下回っています。");
  const project = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!).working.project, artifactSessionKey);
  const start = project.route_nodes[0];
  await page.getByText("地形点KML・DEMの取得状況と出典", { exact: true }).click();
  await page.getByLabel("資料の作成元・識別子", { exact: true }).fill("Synthetic SEA fixture");
  await page.getByLabel("DEMとの標高基準・測量時点の照合根拠", { exact: true }).fill("TP fixture, same epoch");
  await page.getByRole("checkbox", { name: "KML内の全点の標高値は地表の標高で、単位はm、基準はT.P.（東京湾平均海面）であると確認しました。" }).check();
  const upload = page.getByLabel("地形点KML", { exact: true });
  // Hold File.text before parsing: clear and a second import must remain unavailable.
  await page.evaluate(() => {
    const read = File.prototype.text;
    File.prototype.text = async function () {
      await new Promise<void>(resolve => { (window as any).finishTerrainRead = resolve; });
      return read.call(this);
    };
    (window as any).restoreTerrainRead = () => { File.prototype.text = read; };
  });
  await upload.setInputFiles({ name: "terrain.kml", mimeType: "application/xml", buffer: Buffer.from(
    `<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Point><altitudeMode>absolute</altitudeMode><coordinates>${start.longitude_deg},${start.latitude_deg},609.6</coordinates></Point></Placemark></kml>`) });
  const clear = page.getByRole("button", { name: "地形点KMLを解除", exact: true });
  await expect(upload).toBeDisabled();
  await expect(clear).toBeDisabled();
  await page.evaluate(() => { (window as any).restoreTerrainRead(); (window as any).finishTerrainRead(); });
  await expect(first).toContainText("自動値（3000 ft）");
  await expect(input).toHaveValue("1000");
  await expect(upload).toBeEnabled();
  await upload.setInputFiles({ name: "bad.kml", mimeType: "application/xml", buffer: Buffer.from("invalid") });
  await expect(page.getByRole("status").filter({ hasText: "地形点KMLを取り込めません" })).toBeVisible();
  await expect(first).toContainText("自動値（3000 ft）");
  await clear.click();
  await expect(first).toContainText("自動値（1100 ft）");
  await expect(page.getByText(/採用中のKML：/)).toHaveCount(0);
  await page.reload();
  await expect(first).toContainText("自動値（1100 ft）");
});
