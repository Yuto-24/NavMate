import { expect, test, type Page } from "@playwright/test";
import { aipCategories } from "../src/aipAirspace";
import { openProjectMenu } from "./helpers/header";
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

async function expectAirspacePane(page: Page, width: number) {
  const control = page.locator(".planning-pane-scroll > .aip-layer-control");
  await expect(control).toHaveCount(1);
  await expect(page.locator(".map-frame .aip-layer-control")).toHaveCount(0);
  const boxes = await page.evaluate(() => {
    const map = document.querySelector(".map-frame")!.getBoundingClientRect();
    const pane = document.querySelector(".planning-pane")!.getBoundingClientRect();
    const control = document.querySelector(".aip-layer-control")!;
    const route = document.querySelector(".map-route-controls, .route-timeline")!;
    return { map: { top: map.top, right: map.right, bottom: map.bottom },
      pane: { top: pane.top, left: pane.left },
      followsRoute: Boolean(route.compareDocumentPosition(control) & Node.DOCUMENT_POSITION_FOLLOWING),
      overflow: document.documentElement.scrollWidth - innerWidth };
  });
  expect(boxes.followsRoute).toBe(true);
  expect(boxes.overflow).toBeLessThanOrEqual(1);
  if (width > 700) {
    expect(boxes.map.right).toBeLessThanOrEqual(boxes.pane.left + 2);
    expect(Math.abs(boxes.map.top - boxes.pane.top)).toBeLessThanOrEqual(2);
  } else expect(boxes.pane.top).toBeGreaterThanOrEqual(boxes.map.bottom - 1);
}

for (const width of [390, 1100, 1440]) {
  test(`#312 #502 airspace pane preserves creation, Planning, re-edit and reload at ${width}px`, async ({ page }, info) => {
    await mockTiles(page);
    await page.setViewportSize({ width, height: 1100 });
    const requests: string[] = [];
    page.on("request", request => requests.push(request.url()));
    await start(page);
    const civil = page.locator(".aip-Civil_training_and_testing_areas");
    const pca = page.getByLabel("宮崎特別管制区（PCA）", { exact: true });
    const summary = page.getByText("空域表示", { exact: true });
    const control = page.locator(".aip-layer-control");
    await expect(control).not.toHaveAttribute("open");
    await expect(civil).toHaveCount(132);
    await expect(page.locator(".aip-airspace.leaflet-interactive")).toHaveCount(0);
    await expect(page.locator(".rjfm-training-airspace")).toHaveCount(0);
    await expectAirspacePane(page, width);
    await summary.click();
    await expectAirspacePane(page, width);
    await expect(control).not.toContainText("AIRAC");
    await expect(control).not.toContainText("Shapefile");
    const styles = await control.locator("label").evaluateAll(labels => labels.map(label => {
      const style = getComputedStyle(label);
      const input = label.querySelector("input")!;
      return { height: label.getBoundingClientRect().height, font: style.fontFamily,
        weight: style.fontWeight, select: style.getPropertyValue("user-select") || style.getPropertyValue("-webkit-user-select"), checkbox: input.getBoundingClientRect().height };
    }));
    for (const style of styles) {
      expect(style.height).toBeLessThanOrEqual(36);
      expect(style.font).toContain("Noto Sans JP");
      expect(style.weight).toBe("500");
      expect(style.select).toBe("none");
      expect(style.checkbox).toBe(17);
    }
    // Fresh devices show exactly the three requested AIP categories plus PCA.
    const defaults = ["Civil_training_and_testing_areas", "Approach_control_area_CIVIL", "Restricted_area_Airspace_restrictions"];
    for (const [id, label] of aipCategories) {
      await expect(page.getByLabel(label, { exact: true })).toBeChecked({ checked: defaults.includes(id) });
      if (defaults.includes(id)) await expect(page.locator(`.aip-${id}`).first()).toBeAttached();
      else await expect(page.locator(`.aip-${id}`)).toHaveCount(0);
    }
    await expect(pca).toBeChecked();
    await pca.focus();
    await page.keyboard.press("Space");
    await expect(pca).not.toBeChecked();
    await page.keyboard.press("Space");
    await expect(pca).toBeChecked();
    await summary.click();
    await selectAirport(page, "RJFM");
    await selectAirport(page, "RJFK");
    await summary.click();
    await expect(control).toHaveAttribute("open");
    await page.getByRole("button", { name: "経路を確定", exact: true }).click();
    await expect(page.locator(".route-workspace.is-route-building")).toHaveCount(0);
    await expect(control).not.toHaveAttribute("open");
    await expectAirspacePane(page, width);
    await summary.click();
    await expectAirspacePane(page, width);
    await expect(page.locator(".rjfm-pca-boundary")).toHaveCount(1);
    await expect(page.locator(".rjfm-pca-exclusion")).toHaveCount(1);
    await pca.uncheck();
    await expect(page.locator(".rjfm-pca-boundary, .rjfm-pca-exclusion")).toHaveCount(0);
    await pca.check();
    await expect(page.locator(".rjfm-pca-boundary, .rjfm-pca-exclusion")).toHaveCount(2);
    for (const background of ["map", "imagery"]) {
      await page.getByLabel("背景地図").selectOption(background);
      for (const [id, label] of aipCategories) {
        await test.step(`${background}: ${label}`, async () => {
          const checkbox = page.getByLabel(label, { exact: true });
          await checkbox.check();
          const shape = page.locator(`.aip-${id}`).first();
          await expect(shape).toBeAttached();
          const stroke = await shape.evaluate(el => getComputedStyle(el).stroke);
          await expect(checkbox).toHaveCSS("border-top-color", stroke);
          await expect(shape).not.toHaveAttribute("stroke", "#315caa");
          await expect(shape).toHaveAttribute("stroke-width", background === "imagery" ? "2.5" : "1.5");
          await checkbox.uncheck();
          await expect(page.locator(`.aip-${id}`)).toHaveCount(0);
        });
      }
      for (const selector of [".rjfm-pca-boundary", ".rjfm-pca-exclusion"]) {
        const stroke = await page.locator(selector).evaluate(el => getComputedStyle(el).stroke);
        await expect(pca).toHaveCSS("border-top-color", stroke);
      }
    }
    await page.getByLabel("背景地図").selectOption("map");
    await pca.uncheck();
    await page.getByLabel("回廊", { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`airspace-planning-${width}.png`), fullPage: true });
    await summary.click();
    await page.getByRole("button", { name: "経路を編集", exact: true }).click();
    await expect(page.locator(".route-workspace.is-route-building")).toBeVisible();
    await summary.click();
    await expectAirspacePane(page, width);
    await expect(pca).not.toBeChecked();
    await expect(page.locator(".aip-airspace, .rjfm-pca-boundary, .rjfm-pca-exclusion")).toHaveCount(0);
    await pca.check();
    await expect(page.locator(".rjfm-pca-boundary, .rjfm-pca-exclusion")).toHaveCount(2);
    await pca.uncheck();
    await page.getByRole("button", { name: "経路を確定", exact: true }).click();
    await expect(page.locator(".route-workspace.is-route-building")).toHaveCount(0);
    await expect(control).not.toHaveAttribute("open");
    await page.getByRole("button", { name: "経路を編集", exact: true }).click();
    await page.getByRole("button", { name: "地図を全画面表示", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "全画面の経路地図" })).toBeVisible();
    await expect(page.locator(".map-frame .aip-layer-control")).toHaveCount(0);
    await page.getByRole("button", { name: "地図の全画面表示を終了", exact: true }).click();
    await start(page);
    await summary.click();
    await expect(pca).not.toBeChecked();
    await expect(page.locator(".aip-airspace, .rjfm-pca-boundary, .rjfm-pca-exclusion")).toHaveCount(0);
    await expect(control.getByRole("checkbox", { checked: true })).toHaveCount(0);
    await expectAirspacePane(page, width);
    expect(requests.some(url => url.includes('/reference/aip/Civil_training_and_testing_areas-'))).toBe(true);
    expect(requests.some(url => url.includes('kokuarea_minkankunren'))).toBe(false);
  });
}

for (const hidden of [[], ["Civil_training_and_testing_areas", "FIR"]]) {
  test(`#312 #502 existing AIP preference ${JSON.stringify(hidden)} survives reload and Project switches`, async ({ page }) => {
    await mockTiles(page);
    await start(page);
    await page.evaluate(hidden => localStorage.setItem("autonavlog.aip-layers.v1", JSON.stringify(hidden)), hidden);
    await start(page);
    const assertSavedPreference = async () => {
      await page.getByText("空域表示", { exact: true }).click();
      for (const [id, label] of aipCategories) {
        await expect(page.getByLabel(label, { exact: true })).toBeChecked({ checked: !hidden.includes(id) });
      }
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.aip-layers.v1")!))).toEqual(hidden);
      await page.getByText("空域表示", { exact: true }).click();
    };
    await assertSavedPreference();
    await selectAirport(page, "RJFM");
    await selectAirport(page, "RJFK");
    await page.getByRole("button", { name: "経路を確定", exact: true }).click();
    await openProjectMenu(page);
    await page.getByLabel("プロジェクト", { exact: true }).fill("Airspace preference");
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
    await page.getByRole("button", { name: "新規", exact: true }).click();
    await assertSavedPreference();
    await openProjectMenu(page);
    await page.getByLabel("保存済み", { exact: true }).selectOption({ label: "Airspace preference" });
    await page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true }).click();
    await expect(page.locator(".route-workspace.is-route-building")).toHaveCount(0);
    await assertSavedPreference();
    await start(page);
    await assertSavedPreference();
  });
}
