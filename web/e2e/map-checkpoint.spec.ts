import { expect, test, type Page } from "@playwright/test";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";

const routeKml = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>RJFM-RJFO</name>
<LineString><coordinates>131.4486111111,31.8772222222,0 131.5,32.4,0 131.65,33.1,0 131.7,33.4,0 131.7372222222,33.4794444444,0</coordinates></LineString>
</Placemark></Document></kml>`;

async function importLocalRoute(page: Page) {
  await page.goto("/");
  await enterImportWorkflow(page);
  await page.locator('#route-file').setInputFiles({ name: "map-interaction.kml", mimeType: "application/vnd.google-earth.kml+xml", buffer: Buffer.from(routeKml) });
  await confirmImportedDraft(page);
  await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.getByLabel("ETD JST", { exact: true }).fill("09:00");
  await expect(page.getByRole("button", { name: "チェックポイントを追加" })).toBeEnabled();
}

test.beforeEach(async ({ page, context }) => {
  await context.route("**/api/**", route => route.abort());
});

// Test fill and stroke hit locations independently against bundled AIP geometry.
for (const [geometry, selector] of [
  ["polygons", ".aip-Civil_training_and_testing_areas"],
  ["boundaries", ".aip-Civil_training_and_testing_areas"],
] as const) {
  test(`AIP display-only ${geometry} pass hover and drag through to the map`, async ({ page, isMobile }) => {
    test.skip(isMobile, "Mouse hover/pan is covered in both desktop engines");
    await page.setViewportSize({ width: 1440, height: 1000 });
    await importLocalRoute(page);
    await expect(page.locator(".aip-Civil_training_and_testing_areas")).toHaveCount(132);
    await expect(page.locator(".aip-Civil_training_and_testing_areas").first()).toHaveAttribute("stroke", "#b82d83");
    const trainingPaths = page.locator(".aip-Civil_training_and_testing_areas");
    expect(await trainingPaths.evaluateAll(paths => paths.every(path =>
      !path.classList.contains("leaflet-interactive") && getComputedStyle(path).pointerEvents === "none",
    ))).toBe(true);
    await expect(page.locator(".rjfm-pca-boundary")).toHaveClass(/leaflet-interactive/);
    await expect(page.locator(".rjfm-pca-exclusion")).toHaveClass(/leaflet-interactive/);

    const map = page.locator(".route-map");
    await map.scrollIntoViewIfNeeded();
    // Use real SVG geometry, including clipping, rather than dragging an arbitrary map point.
    const point = await map.evaluate((element, { selector, geometry }) => {
      const bounds = element.getBoundingClientRect();
      for (const path of element.querySelectorAll<SVGPathElement>(selector)) {
        const matrix = path.getScreenCTM();
        if (!matrix) continue;
        if (geometry === "boundaries") {
          // A coarse screen grid can miss a thin stroke after a fractional pan.
          // Sample the actual path centerline, still checking stroke and clipping.
          const length = path.getTotalLength();
          for (let distance = 0; distance <= length; distance += 1) {
            const local = path.getPointAtLength(distance);
            const point = local.matrixTransform(matrix);
            if (point.x < bounds.left + 50 || point.x >= bounds.right - 60
              || point.y < bounds.top + 50 || point.y >= bounds.bottom - 60) continue;
            if (path.isPointInStroke(local)
              && !document.elementFromPoint(point.x, point.y)?.closest(".leaflet-control, .leaflet-marker-icon")) {
              return { x: point.x, y: point.y };
            }
          }
          continue;
        }
        for (let x = bounds.left + 50; x < bounds.right - 60; x += 3) {
          for (let y = bounds.top + 50; y < bounds.bottom - 60; y += 3) {
            const local = new DOMPoint(x, y).matrixTransform(matrix.inverse());
            const inside = path.isPointInFill(local);
            if (inside && !document.elementFromPoint(x, y)?.closest(".leaflet-control, .leaflet-marker-icon")) {
              return { x, y };
            }
          }
        }
      }
      return null;
    }, { selector, geometry });
    expect(point, `visible geometry for ${selector}`).not.toBeNull();
    await page.mouse.move(point!.x, point!.y);
    await expect(page.locator(".leaflet-tooltip").filter({ hasText: /KS4-/ })).toHaveCount(0);
    const pane = map.locator(".leaflet-map-pane");
    const before = await pane.getAttribute("style");
    await page.mouse.down();
    await page.mouse.move(point!.x + 35, point!.y + 25, { steps: 6 });
    await page.mouse.up();
    await expect.poll(() => pane.getAttribute("style")).not.toBe(before);
    await expect(pane).not.toHaveClass(/leaflet-pan-anim/);
    expect(await page.evaluate(() => window.getSelection()?.toString() ?? "")).toBe("");
    await expect(trainingPaths).toHaveCount(132);
  });
}

test("PCA notice uses converted feet while operational limits, geometry and acquisition feedback remain distinct", async ({ page }, info) => {
  await page.route("**/xyz/dem_png/**", route => route.fulfill({ status: 404, body: "fixture missing" }));
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/reference/aip/Civil_training_and_testing_areas-*.geojson", async route => {
    await pending;
    await route.fallback();
  });
  const legend = page.getByRole("group", { name: "RJFMガイダンス凡例" });
  await Promise.all([
    importLocalRoute(page),
    (async () => {
      try {
        await page.getByText("空域表示", { exact: true }).click({ timeout: 120_000 });
        await expect(page.locator(".aip-layer-options")).toContainText("AIP空域を読み込み中…");
      } finally {
        release();
      }
    })(),
  ]);
  await expect(page.locator(".aip-Civil_training_and_testing_areas")).toHaveCount(132);
  await page.getByRole("button", { name: "RJFM空域凡例を表示", exact: true }).click();
  await expect(legend).not.toContainText("区画を表示");
  await expect(legend).not.toContainText("民間訓練試験空域 KS4（GSI）");
  await expect(legend).toContainText("PCA：約656–2,625 ft（200–800 m）");
  const boundary = page.locator(".rjfm-pca-boundary");
  await expect(boundary).toHaveAttribute("stroke", "#a45b13");
  await boundary.dispatchEvent("mouseover");
  await expect(page.getByRole("tooltip").filter({ hasText: "宮崎特別管制区（PCA）" })).toContainText("原告示高度 約656–2,625 ft（200–800 m）");
  await expect(page.getByRole("tooltip").filter({ hasText: "宮崎特別管制区（PCA）" })).toContainText("運用判定 656–2,700 ft MSL（利用者承認値）");
  await boundary.dispatchEvent("mouseout");
  const exclusion = page.locator(".rjfm-pca-exclusion");
  await expect(exclusion).toHaveCount(1);
  await exclusion.dispatchEvent("mouseover");
  await expect(page.getByRole("tooltip").filter({ hasText: "中心除外" })).toHaveCount(0);
  await exclusion.dispatchEvent("mouseout");
  await expect(legend).not.toContainText("中心除外");
  for (const width of [390, 1100, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page).toHaveTitle(/NavMate/);
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
    await expect(page.locator(".brand-subtitle")).not.toContainText(" / Local");
    await expect(page.locator(".aip-layer-options")).not.toContainText("Shapefile");
    const boxes = await page.evaluate(() => [".map-frame", ".planning-pane"].map(selector => {
      const r = document.querySelector(selector)!.getBoundingClientRect();
      return { x:r.x,y:r.y,width:r.width,height:r.height };
    }));
    for(const b of boxes) {expect(b.width).toBeGreaterThan(0);expect(b.height).toBeGreaterThan(0);}
    if(width<=700) expect(boxes[1]!.y).toBeGreaterThanOrEqual(boxes[0]!.y+boxes[0]!.height-1);
    else {expect(boxes[1]!.x).toBeGreaterThanOrEqual(boxes[0]!.x+boxes[0]!.width-1);expect(Math.abs(boxes[0]!.y-boxes[1]!.y)).toBeLessThanOrEqual(1);}
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.locator(".map-frame").screenshot({ path: info.outputPath(`pca-${width}.png`) });
  }
  await page.route("**/reference/aip/Civil_training_and_testing_areas-*.geojson", route => route.abort());
  await page.reload();
  await expect(page.getByRole("button", { name: "RJFM空域凡例を表示", exact: true })).toHaveAttribute("aria-expanded", "false");
  await page.getByText("空域表示", { exact: true }).click();
  await expect(page.locator(".aip-layer-options")).toContainText("AIP空域を読み込めませんでした。");
  for (const width of [390, 1440]) {
    await page.setViewportSize({width,height:950});
    await page.screenshot({path:info.outputPath(`airspace-failure-${width}.png`),fullPage:true});
  }
  await expect(page.locator(".aip-Civil_training_and_testing_areas")).toHaveCount(0);
  await expect(boundary).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("green theme keeps readable controls, keyboard selection and aviation colors", async ({ page }, info) => {
  await importLocalRoute(page);
  for (const [name, altitude] of [["RJFM", "6500"], ["WP1", "7500"], ["WP2", "6500"]]) {
    await page.getByLabel(`${name}出発Legの計画高度`, { exact: true }).fill(altitude!);
  }
  const contrast = (first: string, second: string) => {
    const luminance = (color: string) => color.match(/[\d.]+/g)!.slice(0, 3)
      .map(value => Number(value) / 255)
      .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
      .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index]!, 0);
    const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
    return (values[0]! + 0.05) / (values[1]! + 0.05);
  };
  const header = page.locator(".app-header");
  const primary = page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ });
  const selected = page.locator('.descent-rate-segments input:checked + span');
  for (const width of [390, 1100, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(header).toHaveCSS("background-color", "rgb(255, 255, 255)");
    await expect(primary).toBeEnabled();
    await page.mouse.move(0, 0);
    await expect(primary).toHaveCSS("background-color", "rgb(194, 65, 12)");
    const savedProjects = header.getByLabel("保存済み", { exact: true });
    for (const element of [header, primary, selected, savedProjects]) {
      const colors = await element.evaluate(el => {
        const style = getComputedStyle(el);
        return [style.color, style.backgroundColor];
      });
      expect(contrast(colors[0]!, colors[1]!)).toBeGreaterThanOrEqual(4.5);
    }
    await primary.hover();
    await expect(primary).toHaveCSS("background-color", "rgb(154, 52, 18)");
    expect(contrast(await primary.evaluate(el => getComputedStyle(el).color), "rgb(154, 52, 18)")).toBeGreaterThanOrEqual(4.5);
    await expect(selected).toHaveCSS("text-decoration-line", "underline");
    const standard = page.locator('.descent-rate-segments input[value="500"]');
    await standard.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(standard).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(page.locator('.descent-rate-segments input[value="1000"]')).toBeChecked();
    await page.keyboard.press("ArrowLeft");
    await expect(standard).toBeChecked();
    await expect(selected).toHaveCSS("background-color", "rgb(34, 92, 77)");
    await expect(selected).toHaveCSS("box-shadow", "rgb(255, 255, 255) 0px 0px 0px 3px inset");
    await page.locator(".descent-rate-control").screenshot({ path: info.outputPath(`green-selection-${width}.png`) });
    const newButton = header.getByRole("button", { name: "新規", exact: true });
    await newButton.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(newButton).toBeFocused();
    await expect(newButton).toHaveCSS("outline-style", "solid");
    await expect(newButton).toHaveCSS("outline-color", "rgb(34, 92, 77)");
    expect(contrast(await newButton.evaluate(el => getComputedStyle(el).outlineColor), "rgb(255, 255, 255)")).toBeGreaterThanOrEqual(3);
    await header.screenshot({ path: info.outputPath(`green-header-${width}.png`) });
    await page.screenshot({ path: info.outputPath(`green-workspace-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1600, height: 1000 });
  const information = header.getByRole("button", { name: /^その他/ });
  // Exercise the existing warning CSS state even when KNOWN_ISSUES is empty.
  await information.evaluate(el => el.classList.add("information-warning"));
  await information.hover();
  const warningColors = await information.evaluate(el => [getComputedStyle(el).color, getComputedStyle(el).backgroundColor]);
  expect(contrast(warningColors[0]!, warningColors[1]!)).toBeGreaterThanOrEqual(4.5);
  await header.screenshot({ path: info.outputPath("green-warning-1600.png") });
  await information.evaluate(el => el.classList.remove("information-warning"));
  await header.getByRole("button", { name: /^アカウント(?:（|$)/ }).click();
  const dialog = page.getByRole("dialog", { name: "アカウント", exact: true });
  await page.keyboard.press("Tab");
  const close = dialog.getByRole("button", { name: "アカウントを閉じる", exact: true });
  await close.focus();
  await expect(close).toHaveCSS("outline-color", "rgb(34, 92, 77)");
  expect(contrast(await close.evaluate(el => getComputedStyle(el).outlineColor), "rgb(255, 255, 255)")).toBeGreaterThanOrEqual(3);
  await dialog.screenshot({ path: info.outputPath("green-account-focus.png") });
  await close.click();
  await primary.click();
  await expect(page.getByRole("button", { name: "チェックポイントを追加" })).toBeEnabled();
  await expect(page.locator(".rjfm-pca-boundary")).toHaveAttribute("stroke", "#a45b13");
  await expect(page.locator(".aip-Civil_training_and_testing_areas").first()).toHaveAttribute("stroke", "#b82d83");

});
