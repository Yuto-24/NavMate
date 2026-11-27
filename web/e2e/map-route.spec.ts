import { clickMapCoordinate } from "./helpers/mapCoordinate";
import { expectPlanningLayout } from "./helpers/planningLayout";
import { openProjectMenu } from "./helpers/header";
import { confirmImportedDraft } from "./helpers/importWorkflow";
import { mapZoom, revealAirport, selectAirport, zoomMapTo } from "./helpers/mapCandidates";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { deferPlanningRender, installPlanningRenderDelay } from "./helpers/planningRender";
import { artifactSessionKey } from "./helpers/localArtifact";

test.beforeEach(async ({ page }) => {
  page.on("console", message => { if (message.type() === "error") console.log(message.text()); });
  await page.addInitScript(() => {
    const Original = Worker;
    window.Worker = class extends Original {
      constructor(url: string | URL, options?: WorkerOptions) {
        super(url, options);
        this.addEventListener("message", event => {
          if (event.data?.name === "throw") console.error("Local worker failure", String(event.data.value?.value?.message ?? event.data.value));
        });
      }
    };
  });
});

async function start(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible({ timeout: 90_000 });
}
const strip = (page: Page) => page.getByRole("list", { name: "経路リスト" });
async function pick(page: Page, latitude: number, longitude: number) {
  const view = await page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!));
  const frame = (await page.locator(".route-map").boundingBox())!;
  const project = (lat: number, lon: number) => {
    const scale = 256 * 2 ** view.zoom;
    const sine = Math.sin(lat * Math.PI / 180);
    return [scale * (lon + 180) / 360, scale * (0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI))];
  };
  const target = project(latitude, longitude), center = project(view.latitude, view.longitude);
  await page.mouse.click(frame.x + frame.width / 2 + target[0]! - center[0]!, frame.y + frame.height / 2 + target[1]! - center[1]!);
}

test("Leaflet zoom controls contain long-press styling without blocking map interaction", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await start(page);
  const zoomButtons = page.locator("#route-map-frame .leaflet-control-zoom a");
  await expect(zoomButtons).toHaveCount(2);
  const attribution = page.locator("#route-map-frame .leaflet-control-attribution");
  const leaflet = attribution.getByRole("link", { name: "Leaflet", exact: true });
  const osm = attribution.getByRole("link", { name: "OpenStreetMap contributors", exact: true });
  await expect(leaflet).toBeVisible();
  await expect(osm).toBeVisible();
  await expect(leaflet).toHaveAttribute("href", "https://leafletjs.com");
  await expect(osm).toHaveAttribute("href", "https://www.openstreetmap.org/copyright");
  const frame = page.locator("#route-map-frame");
  expect(await frame.evaluate(root => [root, ...root.querySelectorAll("*")].every(element => {
    const style = getComputedStyle(element);
    return (style.userSelect || style.getPropertyValue("-webkit-user-select")) === "none"
      && (!CSS.supports("-webkit-touch-callout", "none") || style.getPropertyValue("-webkit-touch-callout") === "none");
  }))).toBe(true);
  const stylesheetHref = await page.locator('link[rel="stylesheet"]').getAttribute("href");
  expect(stylesheetHref).not.toBeNull();
  const stylesheet = await page.request.get(new URL(stylesheetHref!, page.url()).href);
  expect(stylesheet.ok()).toBe(true);
  expect(await stylesheet.text()).toMatch(
    /\.map-frame\s+\*\s*\{[^}]*-webkit-touch-callout:\s*none/s,
  );
  await expect(page.locator("body")).not.toHaveCSS("user-select", "none");
  await expect(page.locator(".map-route-controls h2")).not.toHaveCSS("user-select", "none");

  // Prepare the route before panning, while its airport markers are in view.
  await page.getByRole("button", { name: "Zoom out" }).click();
  await selectAirport(page, "RJFM");
  await selectAirport(page, "RJFK");
  const map = page.locator(".route-map");
  await map.scrollIntoViewIfNeeded();
  const mapBounds = (await map.boundingBox())!;
  await expect(map).toHaveCSS("touch-action", "none");
  const getMapViewport = () => page.evaluate(() => localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last"));
  await expect.poll(getMapViewport).not.toBeNull();
  const centerBeforePan = await getMapViewport();
  await page.mouse.move(mapBounds.x + mapBounds.width / 2, mapBounds.y + mapBounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(mapBounds.x + mapBounds.width / 2 + 28, mapBounds.y + mapBounds.height / 2 + 16, { steps: 3 });
  await page.mouse.up();
  await expect.poll(getMapViewport).not.toBe(centerBeforePan);

  const initialZoom = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!).zoom as number,
  );
  await page.getByRole("button", { name: "Zoom out" }).click();
  await expect.poll(async () => page.evaluate(() =>
    JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!).zoom as number,
  )).toBe(initialZoom - 1);

  await page.getByRole("button", { name: "経路を確定", exact: true }).click();
  await expect(frame.getByRole("button", { name: "RJFM空域凡例を表示", exact: true })).toBeVisible();
  const legend = frame.getByRole("group", { name: "RJFMガイダンス凡例" });
  expect(await legend.locator("*").evaluateAll(elements => elements.every(element => {
    const style = getComputedStyle(element);
    return (style.userSelect || style.getPropertyValue("-webkit-user-select")) === "none"
      && (!CSS.supports("-webkit-touch-callout", "none") || style.getPropertyValue("-webkit-touch-callout") === "none");
  }))).toBe(true);
  await expect(page.getByRole("complementary", { name: "RJFM空域データ注記" })).toHaveCount(0);
  await expect(attribution).toBeVisible();
  await expect(osm).toBeVisible();
  await expect(attribution).toHaveCSS("user-select", "none");
});

for (const width of [1100, 1440]) {
  test(`MAP to Planning and NAV LOG, reload, save and reopen at ${width}px`, async ({ page }, info) => {
    test.setTimeout(360_000);
    const local = info.config.metadata.applicationMode === "local";
    if (local) await installPlanningRenderDelay(page);
    const api: string[] = [];
    if (local) await page.context().route("**/api/**", route => { api.push(route.request().url()); return route.abort(); });
    await page.setViewportSize({ width, height: 1100 });
    await start(page);
    await expect(page.getByLabel("DATE", { exact: true })).toHaveCount(0);
    const draftInput = (await page.locator(".input-rail").boundingBox())!;
    const draftRoute = (await page.locator(".route-workspace").boundingBox())!;
    await expectPlanningLayout(page, width);
    const before = await page.locator(".route-map").boundingBox();
    expect(before!.height).toBeGreaterThanOrEqual(300);
    await revealAirport(page, "RJFM");
    const viewport = await page.evaluate(() => localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last"));
    await selectAirport(page, "RJFM");
    await expect(strip(page).locator("li")).toHaveCount(1);
    expect(await page.evaluate(() => localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last"))).toBe(viewport);
    await zoomMapTo(page, 8);
    await page.getByRole("button", { name: "Zoom out" }).click();
    await expect.poll(async () => page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!).zoom)).toBe(7);
    await pick(page, 32.115635, 130.337678);
    await expect(strip(page)).toContainText("WP1");
    await pick(page, 32.893463, 130.536873);
    await pick(page, 33.029605, 130.444088);
    await expect(strip(page).locator("li")).toHaveCount(4);
    await expect(page.getByRole("button", { name: "経路を確定", exact: true })).toBeDisabled();
    await page.locator(".route-workspace").screenshot({ path: info.outputPath("map-draft.png") });
    await page.reload();
    await expect(page.getByText("NavMateを起動しています", { exact: true })).toHaveCount(0, { timeout: 120_000 });
    await expect(strip(page).locator("li")).toHaveCount(4, { timeout: 90_000 });
    await selectAirport(page, "RJFS");
    await expect(strip(page).locator("li")).toHaveCount(5);
    if (local) await deferPlanningRender(page);
    await page.getByRole("button", { name: "経路を確定", exact: true }).click();
    await expect(page.getByLabel("DATE", { exact: true })).toBeInViewport();
    await expect(page.getByLabel("DATE", { exact: true })).toBeFocused();
    if (local) {
      expect(await page.evaluate(() => (window as any).planningRenderDelay.delayed)).toBeGreaterThan(0);
      expect(await page.evaluate(() => (window as any).planningRenderDelay.focusFrameBeforeCommit)).toBe(true);
    }
    await expect(page.locator(".route-workspace.is-route-building")).toHaveCount(0);
    const input = (await page.locator(".input-rail").boundingBox())!;
    const route = (await page.locator(".route-workspace").boundingBox())!;
    const readiness = (await page.locator(".status-rail").boundingBox())!;
    await expectPlanningLayout(page, width);
    await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
    await expect(page.getByLabel("気象モード")).toHaveValue("FORECAST");
    await page.getByLabel("気象モード").selectOption("FTD");
    for (const [name, altitude] of [["RJFM", "6500"], ["WP1", "7500"], ["WP2", "6500"]]) {
      await page.getByLabel(`${name}出発Legの計画高度`, { exact: true }).fill(altitude!);
    }
    await page.getByRole("button", { name: "チェックポイントを追加", exact: true }).click();
    await clickMapCoordinate(page, 32.0, 130.9);
    const cp = page.locator(".checkpoint-form");
    await cp.getByLabel("名称", { exact: true }).fill("MAP CP");
    await cp.getByRole("button", { name: "追加", exact: true }).click();
    await expect(page.getByRole("button", { name: "MAP CPを編集", exact: true })).toBeVisible();
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    await expect(page.locator(".nav-log-table")).toBeVisible();
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
    await page.reload();
    await expect(page.getByText("NavMateを起動しています", { exact: true })).toHaveCount(0, { timeout: 120_000 });
    await expect(page.locator(".nav-log-table")).toBeVisible();
    await expect(page.locator(".route-workspace.is-route-building")).toHaveCount(0);
    const projectId = await page.getByLabel("保存済み", { exact: true }).inputValue();
    const savedView = await page.evaluate(id => localStorage.getItem(`autonavlog.map-viewport.v1.anonymous.project.${id}`), projectId);
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "新規", exact: true }).click();
    await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible({ timeout: 90_000 });
    expect(await page.evaluate(() => localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last"))).toBe(savedView);
    await selectAirport(page, "RJFM");
    await zoomMapTo(page, (await mapZoom(page)) + 1);
    await openProjectMenu(page);
    await page.getByLabel("保存済み", { exact: true }).selectOption(projectId);
    const cancelledLoad = new Promise<void>(resolve => page.once("dialog", async dialog => {
      await dialog.dismiss();
      resolve();
    }));
    await openProjectMenu(page);
    await page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true }).click();
    await cancelledLoad;
    await expect(page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true })).toBeEnabled();
    await expect(strip(page).locator("li")).toHaveCount(1);
    page.once("dialog", dialog => dialog.accept());
    await openProjectMenu(page);
    await page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true }).click();
    await expect(page.locator(".nav-log-table")).toBeVisible();
    await expect.poll(() => page.evaluate(() => localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last"))).toBe(savedView);
    // A synced/older Project without a device preference must not open at another route.
    await page.evaluate(id => {
      localStorage.removeItem(`autonavlog.map-viewport.v1.anonymous.project.${id}`);
      localStorage.setItem("autonavlog.map-viewport.v1.anonymous.last", JSON.stringify({ latitude: 35.68, longitude: 139.76, zoom: 12 }));
    }, projectId);
    await page.reload();
    await expect(page.locator(".nav-log-table")).toBeVisible({ timeout: 120_000 });
    await expect.poll(async () => page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!).longitude)).toBeLessThan(132);
    const fitted = await page.evaluate(() => localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last"));
    await page.reload();
    await expect(page.locator(".nav-log-table")).toBeVisible({ timeout: 120_000 });
    expect(await page.evaluate(() => localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last"))).toBe(fitted);
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "新規", exact: true }).click();
    await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
    await page.evaluate(id => {
      localStorage.removeItem(`autonavlog.map-viewport.v1.anonymous.project.${id}`);
      localStorage.setItem("autonavlog.map-viewport.v1.anonymous.last", JSON.stringify({ latitude: 35.68, longitude: 139.76, zoom: 12 }));
    }, projectId);
    await page.reload();
    await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible({ timeout: 120_000 });
    await openProjectMenu(page);
    await page.getByLabel("保存済み", { exact: true }).selectOption(projectId);
    await page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true }).click();
    await expect(page.locator(".nav-log-table")).toBeVisible();
    await expect.poll(async () => page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!).longitude)).toBeLessThan(132);
    expect(api).toEqual([]);
    await page.screenshot({ path: info.outputPath("map-route.png"), fullPage: true });
  });
}

test("MAP to Planning and NAV LOG #523 two legs, CP, save/reload and Google Earth output", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.route("**/xyz/dem_png/**", route => route.fulfill({ status: 404, body: "" }));
  await start(page);
  await selectAirport(page, "RJFO");
  await clickMapCoordinate(page, 33.029605, 130.444088);
  await selectAirport(page, "RJFS");
  await expect(strip(page).locator("li")).toHaveCount(3);
  await page.getByRole("button", { name: "経路を確定", exact: true }).click();
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.locator('input[aria-label$="出発Legの計画高度"]').first().fill("6500");
  await page.getByRole("radio", { name: "1000 fpm", exact: true }).check();
  await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
  const table = page.locator(".nav-log-table");
  await expect(table).toBeVisible();
  const savedState = () => page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!).working, artifactSessionKey);
  const baseline = await savedState();
  expect(baseline.project.sections.map((section: any) => section.phase)).toEqual(["CLIMB", "VISUAL_ARRIVAL"]);
  expect(baseline.outcome.sections.map((section: any) => section.phase)).toEqual(["CLIMB", "CRUISE", "DESCENT", "VISUAL_ARRIVAL"]);
  await expect(table).toContainText("RCA");
  await expect(table).toContainText("EOC");

  await page.getByRole("button", { name: "チェックポイントを追加", exact: true }).click();
  await clickMapCoordinate(page, 33.28, 131.1);
  const cp = page.locator(".checkpoint-form");
  await cp.getByLabel("名称", { exact: true }).fill("TWO LEG CP");
  await cp.getByRole("button", { name: "追加", exact: true }).click();
  await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
  await expect(table).toContainText("TWO LEG CP");
  await expect(page.getByRole("button", { name: "地形を再取得", exact: true })).toBeEnabled();
  const calculated = await savedState();
  expect(calculated.project.route_nodes).toHaveLength(3);
  expect(calculated.project.sections).toHaveLength(2);
  expect(calculated.outcome.check_point_projections).toHaveLength(1);
  expect(calculated.outcome.fuel_plan.bof_gal).toBeCloseTo(baseline.outcome.fuel_plan.bof_gal, 8);
  expect(calculated.outcome.sections.at(-1).cumulative_ete_seconds.automatic_value)
    .toBeCloseTo(baseline.outcome.sections.at(-1).cumulative_ete_seconds.automatic_value, 6);
  // Both CP intervals overlap cruise; VISUAL ARRIVAL has no SEA display.
  // RCA/EOC do not add SEA intervals.
  await expect(table.locator('.nav-log-sea-cell[data-display-text="未確定"]')).toHaveCount(2);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
  await page.reload();
  await expect(page.getByText("NavMateを起動しています", { exact: true })).toHaveCount(0, { timeout: 120_000 });
  await expect(table).toBeVisible();
  const restored = await savedState();
  expect(restored.outcome).toEqual(calculated.outcome);
  expect(restored.project.sections).toEqual(calculated.project.sections);
  expect(restored.project.visual_references).toEqual(calculated.project.visual_references);

  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Google Earth", exact: true }).click();
  const download = await pending;
  const text = readFileSync((await download.path())!, "utf8");
  const kml = await page.evaluate(text => {
    const doc = new DOMParser().parseFromString(text, "application/xml");
    return {
      errors: doc.querySelectorAll("parsererror").length,
      paths: Array.from(doc.querySelectorAll("Placemark")).filter(p => p.querySelector("LineString"))
        .map(p => ({ phase: p.querySelector('Data[name="phase"] value')!.textContent,
          points: p.querySelector("coordinates")!.textContent!.trim().split(/\s+/).map(p => p.split(",").map(Number)) })),
      markers: Array.from(doc.querySelectorAll('Data[name="kind"] value')).map(p => p.textContent),
    };
  }, text);
  expect(kml.errors).toBe(0);
  expect([...new Set(kml.paths.map(path => path.phase))]).toEqual(["CLIMB", "CRUISE", "DESCENT", "VISUAL_ARRIVAL"]);
  expect(kml.markers).toEqual(expect.arrayContaining(["RCA", "EOC", "CHECK_POINT"]));
  for (let index = 1; index < kml.paths.length; index++) {
    expect(kml.paths[index]!.points[0]).toEqual(kml.paths[index - 1]!.points.at(-1));
  }
  const descent = kml.paths.find(path => path.phase === "DESCENT")!;
  expect(descent.points[0]![2]).toBeCloseTo(6500 * 0.3048, 6);
  const arrival = restored.last_calculation.outcome.sections.find((zone: any) => zone.phase === "DESCENT")
    .performance_metadata.target_altitude_ft_msl;
  expect(descent.points.at(-1)![2]).toBeCloseTo(arrival * 0.3048, 6);
});

test("repeated airport occurrence removal, clear and new-work cancellation", async ({ page }) => {
  await start(page);
  await selectAirport(page, "RJFM");
  await zoomMapTo(page, 9);
  await pick(page, 31.98, 131.3);
  await selectAirport(page, "RJFM");
  await pick(page, 32.01, 131.3);
  await selectAirport(page, "RJFM");
  await expect(strip(page).locator("li")).toHaveCount(5);
  await page.getByRole("button", { name: "3番目のRJFMを削除" }).click();
  await expect(strip(page).locator("li")).toHaveCount(4);
  await expect(strip(page).locator("li").last()).toContainText("RJFM");
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "経路をクリア" }).click();
  await expect(strip(page).locator("li")).toHaveCount(4);
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "新規", exact: true }).click();
  await expect(strip(page).locator("li")).toHaveCount(4);
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "経路をクリア" }).click();
  await expect(strip(page)).toHaveCount(0);
});


test("direct airport route survives failed local persistence and can be saved", async ({ page }, info) => {
  test.skip(info.config.metadata.applicationMode !== "local", "Local repository failure path");
  test.setTimeout(180_000);
  await start(page);
  const initialView = await page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!));
  expect(initialView.latitude).toBeCloseTo(31.8772, 2);
  expect(initialView.longitude).toBeCloseTo(131.4486, 2);
  await selectAirport(page, "RJFM");
  await page.getByRole("button", { name: "Zoom out" }).click();
  await selectAirport(page, "RJFK");
  await expect(strip(page).locator("li")).toHaveCount(2);
  await page.evaluate(() => {
    const put = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function(...args) {
      if (this.name === "projects") {
        IDBObjectStore.prototype.put = put;
        throw new DOMException("injected disk failure", "UnknownError");
      }
      return put.apply(this, args);
    };
  });
  await page.getByRole("button", { name: "経路を確定", exact: true }).click();
  await expect(page.getByLabel("DATE", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toBeInViewport();
  await expect(page.locator(".timeline-stop")).toHaveCount(2);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
  await page.reload();
  await expect(page.getByText("NavMateを起動しています", { exact: true })).toHaveCount(0, { timeout: 120_000 });
  await expect(page.locator(".timeline-stop")).toHaveCount(2);
});

for (const width of [1100, 1440]) {
  test(`Issue 235: click OMARU with correct provenance and restore the draft at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 });
    await start(page);
    await expect(page.locator('.map-route-controls .field-hint')).toHaveCount(0);
    await selectAirport(page, "RJFM");
    await zoomMapTo(page, 9);
    const marker = page.locator('.vrep-draft-marker[title="小丸"]');
    for (let attempt = 0; attempt < 12 && !await marker.count(); attempt++) {
      const cluster = page.locator('.candidate-cluster').filter({ has: page.locator('[data-candidates~="RJFM:OMARU"]') });
      await cluster.click();
      await expect(page.locator('.route-map')).not.toHaveClass(/leaflet-zoom-anim/);
    }
    await marker.hover();
    await expect(page.getByRole('tooltip')).toContainText('運用参照図より推定（未検証・誤差0.35NM）');
    await marker.click();
    await expect(strip(page).locator('li')).toHaveCount(2);
    await expect(strip(page).locator('li').nth(1)).toContainText('小丸');
    await page.reload();
    await expect(strip(page).locator('li')).toHaveCount(2);
    await expect(strip(page).locator('li').nth(1)).toContainText('小丸');
    await expect(marker).toHaveCount(1);
    await marker.click();
    // Each explicit click is an occurrence, just like existing VREP markers.
    await expect(strip(page).locator('li')).toHaveCount(3);
    await expect(page).toHaveTitle(/NavMate/);
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    await selectAirport(page, 'RJFO');
    await page.getByRole('button', { name: '経路を確定', exact: true }).click();
    await expect(page.getByLabel('DATE', { exact: true })).toBeVisible();
    const input = (await page.locator('.input-rail').boundingBox())!;
    const route = (await page.locator('.route-workspace').boundingBox())!;
    const readiness = (await page.locator('.status-rail').boundingBox())!;
    await expectPlanningLayout(page, width);
    await page.screenshot({ path: `/tmp/issue235-omaru-map-${width}.png` });
  });
}

for (const manualVor of [false, true]) {
  test(`MAP to Planning and NAV LOG: VOR defaults follow FROM but preserve explicit ${manualVor}`, async ({ page }) => {
    test.setTimeout(180_000);
    await start(page);
    const golden = readFileSync(resolve("../tests/fixtures/issue_43_golden.kml"), "utf8");
    const coordinates = golden.match(/<coordinates>([\s\S]*?)<\/coordinates>/)![1]!.trim().split(/\s+/);
    const points = manualVor ? coordinates : ["130.7194444444,31.8033333333,0", ...coordinates.slice(1)];
    const kml = `<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><LineString><coordinates>${points.join(" ")}</coordinates></LineString></Placemark></Document></kml>`;
    await page.locator('#route-file').setInputFiles({ name: "departure.kml", mimeType: "application/vnd.google-earth.kml+xml", buffer: Buffer.from(kml) });
    await confirmImportedDraft(page);
    const vor = page.getByRole("checkbox", { name: "VOR Tracking Mode", exact: true });
    await expect(page.getByLabel("FROM", { exact: true })).toHaveValue(manualVor ? /^RJFM/ : /^RJFK/);
    await expect(vor).toBeChecked({ checked: !manualVor });
    await vor.setChecked(manualVor);
    // Main's unified KML/MAP flow changes FROM through the confirmed-route draft.
    for (const from of ["RJFM", "RJFK"]) {
      await page.getByRole("button", { name: "経路を編集", exact: true }).click();
      page.once("dialog", dialog => dialog.accept());
      await page.getByRole("button", { name: "経路をクリア", exact: true }).click();
      await revealAirport(page, from);
      await selectAirport(page, from);
      await selectAirport(page, "RJFS");
      await page.getByRole("button", { name: "経路を確定", exact: true }).click();
      await expect(page.getByLabel("FROM", { exact: true })).toHaveValue(new RegExp(`^${from}`));
      await expect(vor).toBeChecked({ checked: manualVor });
    }
    await page.reload();
    await expect(vor).toBeChecked({ checked: manualVor, timeout: 120_000 });
    await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
    await page.getByLabel("気象モード").selectOption("FTD");
    // Confirmed KML routes require valid leg inputs before a named save.
    await expect(page.getByRole("spinbutton", { name: /出発Legの計画高度$/ }).first()).toBeVisible();
    for (const altitude of await page.getByRole("spinbutton", { name: /出発Legの計画高度$/ }).all()) {
      if (await altitude.isEditable() && !(await altitude.inputValue())) await altitude.fill("6500");
    }
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
    const projectId = await page.getByLabel("保存済み", { exact: true }).inputValue();
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "新規", exact: true }).click();
    await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
    await openProjectMenu(page);
    await page.getByLabel("保存済み", { exact: true }).selectOption(projectId);
    await page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true }).click();
    await expect(vor).toBeChecked({ checked: manualVor });
    await expect(page.getByLabel("FROM", { exact: true })).toHaveValue(/^RJFK/);
  });
}

test("MAP to Planning and NAV LOG: new map departures default to VOR except RJFM", async ({ page }) => {
  test.setTimeout(180_000);
  await start(page);
  for (const from of ["RJFK", "RJFM"]) {
    await selectAirport(page, from);
    await selectAirport(page, "RJFS");
    await page.getByRole("button", { name: "経路を確定", exact: true }).click();
    await expect(page.getByLabel("FROM", { exact: true })).toHaveValue(new RegExp(`^${from}`));
    await expect(page.getByRole("checkbox", { name: "VOR Tracking Mode", exact: true }))
      .toBeChecked({ checked: from !== "RJFM" });
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "新規", exact: true }).click();
    await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
  }
});

for (const width of [390, 1100, 1440]) {
  test(`MAP to Planning and NAV LOG: VOR Tracking Mode survives reload at ${width}px`, async ({ page }, info) => {
    test.setTimeout(240_000);
    await page.setViewportSize({ width, height: 1100 });
    await start(page);
    await revealAirport(page, "RJFM");
    await selectAirport(page, "RJFM");
    // Match the established valid MAP fixture, including the penultimate arrival VREP.
    await zoomMapTo(page, 7);
    await pick(page, 32.115635, 130.337678);
    await pick(page, 32.893463, 130.536873);
    await pick(page, 33.029605, 130.444088);
    await selectAirport(page, "RJFS");
    await page.getByRole("button", { name: "経路を確定", exact: true }).click();
    const vor = page.getByRole("checkbox", { name: "VOR Tracking Mode", exact: true });
    await expect(vor).not.toBeChecked();
    await page.locator(".flight-plan-section").screenshot({ path: info.outputPath("vor-planning.png") });
    const layout = await vor.evaluate(checkbox => {
      const bounds = (element: Element) => element.getBoundingClientRect().toJSON();
      const label = checkbox.closest("label")!;
      return {
        checkbox: bounds(checkbox), label: bounds(label), text: bounds(label.querySelector("span")!),
        from: bounds(document.querySelector('input[aria-label="FROM"]')!),
        to: bounds(document.querySelector('input[aria-label="TO"]')!),
        category: bounds([...document.querySelectorAll(".plan-category")].find(e => e.textContent === "航法")!),
        form: bounds(document.querySelector(".flight-plan-section .form-grid")!),
      };
    });
    expect(layout.checkbox.width).toBeCloseTo(17, 0);
    expect(layout.checkbox.height).toBeCloseTo(17, 0);
    expect(layout.text.x).toBeGreaterThan(layout.checkbox.right);
    expect(Math.abs((layout.text.top + layout.text.bottom) / 2
      - (layout.checkbox.top + layout.checkbox.bottom) / 2)).toBeLessThanOrEqual(2);
    expect(layout.label.x).toBeCloseTo(layout.from.x, 0);
    expect(layout.label.top).toBeGreaterThanOrEqual(layout.from.bottom);
    expect(layout.category.top).toBeGreaterThanOrEqual(Math.max(layout.from.bottom, layout.to.bottom));
    expect(layout.label.top).toBeGreaterThanOrEqual(layout.category.bottom);
    expect(layout.label.top - layout.category.bottom).toBeLessThanOrEqual(10);
    expect(layout.label.right).toBeLessThanOrEqual(layout.form.right + 1);
    expect(layout.to.height).toBeCloseTo(layout.from.height, 0);
    expect(layout.to.x).toBeGreaterThan(layout.from.right);
    expect(layout.to.top).toBeCloseTo(layout.from.top, 0);
    // Clicking the visible text must activate the independent checkbox label.
    await page.getByText("VOR Tracking Mode", { exact: true }).click();
    await expect(vor).toBeChecked();
    await page.getByText("VOR Tracking Mode", { exact: true }).click();
    await expect(vor).not.toBeChecked();
    await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
    await page.getByLabel("気象モード").selectOption("FTD");
    for (const [name, altitude] of [["RJFM", "6500"], ["WP1", "7500"], ["WP2", "6500"]]) {
      await page.getByLabel(`${name}出発Legの計画高度`, { exact: true }).fill(altitude!);
    }
    await vor.check();
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    await expect(page.locator(".nav-log-table")).toBeVisible();
    await expect(page.locator(".nav-log-table")).toContainText("MZE");
    await expect(page.getByLabel("TO", { exact: true })).toHaveValue(/^RJFS/);
    // One frame: calculation may still be smoothly scrolling the viewport.
    const [input, route, readiness] = await page.evaluate(() =>
      [".input-rail", ".route-workspace", ".status-rail"].map(selector => {
        const { x, y, width, height } = document.querySelector(selector)!.getBoundingClientRect();
        return { x, y, width, height };
      }),
    );
    for (const region of [input, route, readiness]) {
      expect(region.width).toBeGreaterThan(0);
      expect(region.height).toBeGreaterThan(0);
    }
    await expectPlanningLayout(page, width);
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
    const projectId = await page.getByLabel("保存済み", { exact: true }).inputValue();
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "新規", exact: true }).click();
    await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
    await openProjectMenu(page);
    await page.getByLabel("保存済み", { exact: true }).selectOption(projectId);
    await page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true }).click();
    await expect(vor).toBeChecked();
    await expect(page.locator(".nav-log-table")).toContainText("MZE");
    await page.reload();
    await expect(vor).toBeChecked({ timeout: 120_000 });
    await expect(page.locator(".nav-log-table")).toContainText("MZE");
    await vor.uncheck();
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    await expect(page.locator(".nav-log-table")).toContainText("RJFM");
  });
}
