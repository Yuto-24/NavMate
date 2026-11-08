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
    const input = (await page.locator(".input-rail").boundingBox())!;
    const route = (await page.locator(".route-workspace").boundingBox())!;
    const readiness = (await page.locator(".status-rail").boundingBox())!;
    if (width <= 1240) {
      expect(input.y + input.height).toBeLessThanOrEqual(route.y + 2);
      expect(route.y + route.height).toBeLessThanOrEqual(readiness.y + 2);
    } else {
      expect(input.x + input.width).toBeLessThanOrEqual(route.x + 2);
      expect(route.x + route.width).toBeLessThanOrEqual(readiness.x + 2);
    }
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
