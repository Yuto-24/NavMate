import { expect, test, type Page } from "@playwright/test";
import { selectAirport, zoomMapTo } from "./helpers/mapCandidates";

const preference = "autonavlog.map-background.v1";
const viewport = "autonavlog.map-viewport.v1.anonymous.last";
const image = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64");
const tiles = (page: Page, source: string) => page.locator(`.leaflet-tile[src*="/${source}/"]`);
async function start(page: Page) {
  await page.goto("/");
  await expect(page.getByLabel("背景地図")).toBeVisible({ timeout: 90_000 });
}
async function mockTiles(page: Page) {
  await page.route("https://tile.openstreetmap.org/**", route => route.fulfill({ contentType: "image/png", body: image }));
  await page.route("https://cyberjapandata.gsi.go.jp/**", route => route.fulfill({ contentType: "image/png", body: image }));
}

for (const width of [1100, 1440]) {
  test(`#243 imagery preserves route, viewport, airspace and workflow at ${width}px`, async ({ page }) => {
    await mockTiles(page);
    await page.setViewportSize({ width, height: 1100 });
    await start(page);
    await selectAirport(page, "RJFM");
    await selectAirport(page, "RJFK");
    const strip = page.getByRole("list", { name: "経路リスト" });
    const routeBefore = await strip.innerText();
    const viewBefore = await page.evaluate(key => localStorage.getItem(key), viewport);
    const map = await page.locator(".route-map").elementHandle();
    await page.getByLabel("背景地図").selectOption("imagery");
    await expect(tiles(page, "lndst").first()).toBeVisible();
    expect(await page.evaluate(key => localStorage.getItem(key), viewport)).toBe(viewBefore);
    expect(await strip.innerText()).toBe(routeBefore);
    expect(await map!.evaluate(el => el === document.querySelector(".route-map"))).toBe(true);
    await expect(page.locator(".leaflet-control-attribution")).toContainText("GEBCO");
    await page.getByRole("button", { name: "経路を確定", exact: true }).click();
    await expect(page.locator(".route-workspace.is-route-building")).toHaveCount(0);
    await expect(page.locator(".rjfm-pca-boundary")).toBeAttached();
    const paths = await page.locator(".leaflet-overlay-pane path").elementHandles();
    await page.getByLabel("背景地図").selectOption("map");
    await expect(tiles(page, "lndst")).toHaveCount(0);
    await expect(page.locator(".leaflet-control-attribution")).not.toContainText("GEBCO");
    await page.getByLabel("背景地図").selectOption("imagery");
    // Airspace may finish loading during the switch; existing overlays must survive.
    for (const path of paths) expect(await path.evaluate(element => element.isConnected)).toBe(true);
    const mapBox = (await page.locator(".map-frame").boundingBox())!;
    const pane = (await page.locator(".planning-pane").boundingBox())!;
    expect(mapBox.x + mapBox.width).toBeLessThanOrEqual(pane.x + 2);
    expect(Math.abs(mapBox.y - pane.y)).toBeLessThanOrEqual(2);
    await page.reload();
    await expect(page.getByLabel("背景地図")).toHaveValue("imagery", { timeout: 90_000 });
    await expect(page.locator(".rjfm-pca-boundary")).toBeAttached();
    await page.getByRole("button", { name: "新規", exact: true }).click();
    await expect(page.getByLabel("背景地図")).toHaveValue("imagery");
  });
}

test("#243 missing photos reveal satellite, provider failure reveals map, zoom boundaries remain operable", async ({ page }) => {
  await mockTiles(page);
  await page.addInitScript(({ preference, viewport }) => {
    localStorage.setItem(preference, "imagery");
    localStorage.setItem(viewport, JSON.stringify({ latitude: 31.8772, longitude: 131.4486, zoom: 13 }));
  }, { preference, viewport });
  await start(page);
  await expect(tiles(page, "lndst").first()).toBeVisible();
  await expect(tiles(page, "seamlessphoto")).toHaveCount(0);
  await page.route("**/seamlessphoto/**", route => route.fulfill({ status: 404, body: "missing" }));
  await zoomMapTo(page, 14);
  const photoLayer = page.locator('.leaflet-tile-pane > .leaflet-layer[style*="z-index: 3"]');
  await expect(photoLayer.locator('img[src^="data:image"]')).not.toHaveCount(0);
  await expect(tiles(page, "lndst").first()).toBeVisible();
  await expect(page.locator(".leaflet-control-attribution")).toContainText("© Axelspace");
  await zoomMapTo(page, 19);
  await expect(tiles(page, "lndst").first()).toHaveAttribute("src", /\/lndst\/13\//);
  await page.unroute("**/seamlessphoto/**");
  await zoomMapTo(page, 17);
  await zoomMapTo(page, 19);
  await expect(tiles(page, "seamlessphoto").first()).toHaveAttribute("src", /\/seamlessphoto\/18\//);
  await page.route("https://cyberjapandata.gsi.go.jp/**", route => route.abort());
  // Request a fresh native zoom; decoded images may survive layer remounts.
  await zoomMapTo(page, 12);
  await expect(page.locator('.leaflet-layer[style*="z-index: 2"] img[src^="data:image"]')).not.toHaveCount(0);
  await expect(page.locator('.leaflet-tile[src*="tile.openstreetmap.org"]').first()).toBeVisible();
  await zoomMapTo(page, 2);
  await zoomMapTo(page, 1);
  await expect(tiles(page, "lndst")).toHaveCount(0);
  await expect(page.locator(".leaflet-control-attribution")).not.toContainText("地理院タイル");
  await zoomMapTo(page, 0);
  await expect(page.locator('.leaflet-tile[src*="tile.openstreetmap.org"]').first()).toBeVisible();
});

test("#243 invalid or blocked device preferences do not prevent switching; outside Japan uses map", async ({ page }) => {
  await mockTiles(page);
  const gsiRequests: string[] = [];
  page.on("request", request => { if (request.url().includes("cyberjapandata.gsi.go.jp")) gsiRequests.push(request.url()); });
  await page.addInitScript(({ preference, viewport }) => {
    localStorage.setItem(preference, "invalid");
    localStorage.setItem(viewport, JSON.stringify({ latitude: 51.5, longitude: -0.12, zoom: 14 }));
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (key === preference) throw new DOMException("blocked", "SecurityError");
      return original.call(this, key, value);
    };
  }, { preference, viewport });
  await start(page);
  await expect(page.getByLabel("背景地図")).toHaveValue("map");
  await page.getByLabel("背景地図").selectOption("imagery");
  await expect(page.getByLabel("背景地図")).toHaveValue("imagery");
  await expect(page.locator('.leaflet-tile[src*="tile.openstreetmap.org"]').first()).toBeVisible();
  expect(gsiRequests).toEqual([]);
  await zoomMapTo(page, 15);
});

for (const width of [390, 1100, 1440]) {
  test(`#312 AIP layers survive route creation, Planning, re-edit and reload at ${width}px`, async ({ page }, info) => {
    await mockTiles(page);
    await page.setViewportSize({ width, height: 1100 });
    const requests: string[] = [];
    page.on("request", request => requests.push(request.url()));
    await start(page);
    const civil = page.locator(".aip-Civil_training_and_testing_areas");
    await expect(civil.first()).toBeAttached();
    expect(await civil.count()).toBe(132);
    await expect(page.locator(".aip-airspace.leaflet-interactive")).toHaveCount(0);
    await expect(page.locator(".rjfm-training-airspace")).toHaveCount(0);
    await page.getByText("空域レイヤー", { exact: true }).click();
    await expect(page.getByText("AIRAC有効日：2026-10-29", { exact: true })).toBeVisible();
    await page.getByLabel("民間訓練・試験空域", { exact: true }).uncheck();
    await expect(civil).toHaveCount(0);
    await page.getByLabel("民間訓練・試験空域", { exact: true }).check();
    await page.getByText("空域レイヤー", { exact: true }).click();
    await selectAirport(page, "RJFM");
    await selectAirport(page, "RJFK");
    await page.getByRole("button", { name: "経路を確定", exact: true }).click();
    await expect(page.locator(".route-workspace.is-route-building")).toHaveCount(0);
    await expect(civil).toHaveCount(132);
    await page.getByText("空域レイヤー", { exact: true }).click();
    const menuBox = (await page.locator(".aip-layer-options").boundingBox())!;
    const frameBox = (await page.locator(".map-frame").boundingBox())!;
    expect(menuBox.x).toBeGreaterThanOrEqual(frameBox.x);
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(frameBox.x + frameBox.width);
    expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(frameBox.y + frameBox.height);
    const lastCategory = page.getByLabel("回廊", { exact: true });
    await lastCategory.scrollIntoViewIfNeeded();
    await expect(lastCategory).toBeInViewport();
    const source = page.getByRole("link", { name: "航空情報センター AIP", exact: true });
    await source.scrollIntoViewIfNeeded();
    expect(await source.evaluate(element => {
      const box = element.getBoundingClientRect();
      return element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
    })).toBe(true);
    await page.getByText("空域レイヤー", { exact: true }).click();
    await page.getByRole("button", { name: "経路を編集", exact: true }).click();
    await expect(page.locator(".route-workspace.is-route-building")).toBeVisible();
    await expect(civil).toHaveCount(132);
    await page.getByText("空域レイヤー", { exact: true }).click();
    await page.getByLabel("民間訓練・試験空域", { exact: true }).uncheck();
    await page.getByText("空域レイヤー", { exact: true }).click();
    await page.getByRole("button", { name: "地図を全画面表示", exact: true }).click();
    await page.getByText("空域レイヤー", { exact: true }).click();
    const fullMenu = (await page.locator(".aip-layer-options").boundingBox())!;
    expect(fullMenu.x).toBeGreaterThanOrEqual(0);
    expect(fullMenu.x + fullMenu.width).toBeLessThanOrEqual(width);
    await page.screenshot({ path: info.outputPath(`aip-${width}.png`) });
    await page.reload();
    await start(page);
    await page.getByText("空域レイヤー", { exact: true }).click();
    await expect(page.getByLabel("民間訓練・試験空域", { exact: true })).not.toBeChecked();
    await expect(civil).toHaveCount(0);
    await expect(page.locator(".aip-Restricted_area_Airspace_restrictions").first()).toBeAttached();
    const boxes = await page.evaluate(() => {
      const map = document.querySelector('.map-frame')!.getBoundingClientRect();
      const pane = document.querySelector('.planning-pane')!.getBoundingClientRect();
      return { right: map.right, left: pane.left, delta: Math.abs(map.top - pane.top) };
    });
    if (width > 700) {
      expect(boxes.right).toBeLessThanOrEqual(boxes.left + 2);
      expect(boxes.delta).toBeLessThanOrEqual(2);
    }
    expect(requests.some(url => url.includes('/reference/aip/Civil_training_and_testing_areas-'))).toBe(true);
    expect(requests.some(url => url.includes('kokuarea_minkankunren'))).toBe(false);
  });
}
