import { clickMapCoordinate } from "./helpers/mapCoordinate";
import { expect, test, type Page } from "@playwright/test";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";
import { observeLegacySession } from "./helpers/legacySession";

const local = () => test.info().config.metadata.applicationMode === "local";
const editor = (page: Page) => page.locator(".planning-pane");
const form = (page: Page) => editor(page).locator(".checkpoint-form");
const name = (page: Page) => form(page).getByRole("textbox", { name: /^名称(?:\s|$)/ });
const kml = `<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
<name>RJFM-RJFO</name><LineString><coordinates>
131.4486111111,31.8772222222,0 131.5,32.4,0 131.65,33.1,0
131.7,33.4,0 131.7372222222,33.4794444444,0
</coordinates></LineString></Placemark></Document></kml>`;

async function openEditor(page: Page) {
  await page.getByRole("button", { name: "チェックポイントを追加", exact: true }).click();
  await clickMapCoordinate(page, 32.482176, 131.517485);
  await expect(name(page)).toBeFocused();
}
async function references(page: Page) {
  return page.evaluate(async (isLocal) => isLocal
    ? JSON.parse(sessionStorage.getItem("autonavlog.working-session.v1")!).working.project.visual_references
    : (await (await fetch("/api/state")).json()).project.visual_references, local());
}

test.beforeEach(async ({ page, context }) => {
  if (local()) await context.route("**/api/**", route => route.abort());
  else await observeLegacySession(page);
  // External map layers are unrelated to checkpoint submission.
  await context.route(/https:\/\/.*(?:openstreetmap|gsi\.go\.jp).*/, route => route.fulfill({ status: 200, contentType: "application/json", body: '{"type":"FeatureCollection","features":[]}' }));
  await page.goto("/");
  await expect(page).toHaveTitle(/NavMate/);
  await enterImportWorkflow(page);
  await page.locator('#route-file').setInputFiles({ name: "checkpoint.kml", mimeType: "application/vnd.google-earth.kml+xml", buffer: Buffer.from(kml) });
  await confirmImportedDraft(page);
  await page.getByLabel("気象モード").selectOption("FTD");
  await openEditor(page);
});

for (const width of [1100, 1440]) {
  test(`checkpoint name Enter validates input, respects IME and preserves click at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    const add = form(page).getByRole("button", { name: "追加", exact: true });
    const assertBlocked = async () => {
      await expect(add).toBeDisabled();
      await name(page).press("Enter");
      await expect(form(page)).toBeVisible();
      expect(await references(page)).toHaveLength(0);
    };
    await assertBlocked();
    const inputGeometry = () => name(page).evaluate(input => {
      const box = input.getBoundingClientRect(), parent = input.closest(".checkpoint-form")!.getBoundingClientRect();
      return { left: box.left - parent.left, top: box.top - parent.top, width: box.width, height: parent.height };
    });
    const emptyGeometry = await inputGeometry();
    await expect(form(page).locator(".checkpoint-name-warning")).toHaveCount(0);
    await name(page).fill("   ");
    await assertBlocked();
    await name(page).fill("岩瀬ダム");
    expect(await inputGeometry()).toEqual(emptyGeometry);
    // Coordinates now come only from the map, so malformed numeric coordinate
    // input is no longer a UI path. Domain range/projection validation remains tested separately.
    await expect(form(page).getByLabel("緯度", { exact: true })).toHaveCount(0);
    await expect(form(page).getByLabel("経度", { exact: true })).toHaveCount(0);
    await expect(add).toBeEnabled();

    // Synthetic events cover browser/IME event orderings; they are not physical IME proof.
    await name(page).dispatchEvent("keydown", { key: "Enter", isComposing: true });
    await expect(form(page)).toBeVisible();
    await name(page).dispatchEvent("compositionstart", { data: "いわせ" });
    await name(page).press("Enter");
    await expect(form(page)).toBeVisible();
    await name(page).dispatchEvent("compositionend", { data: "岩瀬" });
    await name(page).dispatchEvent("keydown", { key: "Enter", keyCode: 229 });
    await expect(form(page)).toBeVisible();
    await name(page).dispatchEvent("keydown", { key: "Enter", repeat: true });
    expect(await references(page)).toHaveLength(0);
    await name(page).press("Enter");
    await expect(form(page)).toHaveCount(0);
    await expect(editor(page).getByText("岩瀬ダム", { exact: true })).toBeVisible();
    await expect(page.locator(".checkpoint-confirmed-marker")).toHaveCount(1);
    await expect(editor(page).getByText(/Leg内 .* NM/)).toBeVisible();
    const entered = (await references(page))[0];
    expect(entered.name).toBe("岩瀬ダム");
    const degreesPerPixel = await page.evaluate(() => 360 / (256 * 2 ** JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!).zoom));
    // Real pointer input and Leaflet pixel origins round at the current zoom.
    expect(Math.abs(entered.latitude_deg - 32.482176)).toBeLessThan(degreesPerPixel);
    expect(Math.abs(entered.longitude_deg - 131.517485)).toBeLessThan(degreesPerPixel);
    expect(entered.linked_section_id).toBeTruthy();
    await editor(page).screenshot({ path: info.outputPath(`checkpoint-${width}.png`) });

    await openEditor(page);
    await name(page).fill("クリックCP");
    await add.click();
    await expect(form(page)).toHaveCount(0);
    const clicked = (await references(page))[1];
    // Physical map clicks are quantized to screen pixels, unlike the retired
    // coordinate text fields. Two independently rounded clicks can differ by two pixels.
    // Preserve the selected Leg and geographic target.
    expect(clicked.linked_section_id).toBe(entered.linked_section_id);
    expect(Math.abs(clicked.latitude_deg - entered.latitude_deg)).toBeLessThan(2 * degreesPerPixel);
    expect(Math.abs(clicked.longitude_deg - entered.longitude_deg)).toBeLessThan(2 * degreesPerPixel);
    await editor(page).getByRole("button", { name: "岩瀬ダムを編集", exact: true }).click();
    await clickMapCoordinate(page, 32.65, 131.55);
    await expect(name(page)).toBeFocused();
    // Closing discards coordinate edits as well as names.
    await form(page).getByRole("button", { name: "編集を閉じる", exact: true }).click();
    expect((await references(page))[0]).toEqual(entered);
    await editor(page).getByRole("button", { name: "岩瀬ダムを編集", exact: true }).click();
    await clickMapCoordinate(page, 32.65, 131.55);
    await expect(name(page)).toBeFocused();
    await name(page).fill("岩瀬ダム改");
    await name(page).press("Enter");
    await expect(editor(page).getByText("岩瀬ダム改", { exact: true })).toBeVisible();
    expect(await references(page)).toHaveLength(2);
    const moved = (await references(page))[0];
    expect(moved.id).toBe(entered.id);
    expect(moved.linked_section_id).toBe(entered.linked_section_id);
    // Saved-center projection and the physical click each round to a pixel.
    expect(Math.abs(moved.latitude_deg - 32.65)).toBeLessThan(2 * degreesPerPixel);
    expect(Math.abs(moved.longitude_deg - 131.55)).toBeLessThan(2 * degreesPerPixel);
    await expect(page.locator(".vite-error-overlay, vite-error-overlay")).toHaveCount(0);
    expect(await page.pageErrors()).toEqual([]);
    const consoleErrors = (await page.consoleMessages()).filter(message => message.type() === "error");
    // The unconfigured Legacy migration probe intentionally returns 404.
    expect(consoleErrors.filter(message => !(!local()
      && message.location().url === new URL("/api/account-link", page.url()).href
      && message.text().includes("404")))).toEqual([]);
  });
}

for (const failSave of [false, true]) {
  test(`checkpoint map clicks are ignored while an existing CP save is pending: failure=${failSave}`, async ({ page }) => {
    test.skip(local(), "Legacy response interception delays the shared editor's save");
    await name(page).fill("保存待ちCP");
    await name(page).press("Enter");
    await expect(form(page)).toHaveCount(0);
    const original = (await references(page))[0];
    await editor(page).getByRole("button", { name: "保存待ちCPを編集", exact: true }).click();
    await clickMapCoordinate(page, 32.65, 131.55);
    await expect(name(page)).toBeFocused();
    const draft = () => page.evaluate(() => JSON.parse(sessionStorage.getItem("autonavlog.working-session.v1")!).checkPointDraft);
    await expect.poll(async () => (await draft()).latitude).not.toBe(String(original.latitude_deg));
    const submitted = await draft();
    let release!: () => void;
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route("**/api/project/check-points", async route => {
      await pending;
      if (failSave) await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { message: "Test save failure" } }) });
      else await route.continue();
    }, { times: 1 });
    await form(page).getByRole("button", { name: "保存", exact: true }).click();
    await expect(form(page).getByRole("button", { name: "保存中…", exact: true })).toBeDisabled();
    try {
      await clickMapCoordinate(page, 32.55, 131.53);
      // Let React commit effects after the physical click before checking recovery data.
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect(await draft()).toEqual(submitted);
    } finally {
      release();
    }
    if (failSave) {
      await expect(form(page).getByRole("button", { name: "保存", exact: true })).toBeEnabled();
      expect((await references(page))[0]).toEqual(original);
      // The same draft remains retryable once the failed save has finished.
      await form(page).getByRole("button", { name: "保存", exact: true }).click();
    }
    await expect(form(page)).toHaveCount(0);
    const saved = await references(page);
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ id: original.id, latitude_deg: Number(submitted.latitude), longitude_deg: Number(submitted.longitude), linked_section_id: original.linked_section_id });
    await editor(page).getByRole("button", { name: "保存待ちCPを編集", exact: true }).click();
    await clickMapCoordinate(page, 32.55, 131.53);
    await expect.poll(draft).not.toEqual(submitted);
  });
}

test("checkpoint name Enter locks pending saves and allows retry after failure", async ({ page }) => {
  test.skip(local(), "Legacy response interception verifies the shared editor's pending-save lock");
  let requests = 0;
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/project/check-points", async route => {
    requests++;
    if (requests === 1) {
      await pending;
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Test save failure" }) });
    } else await route.continue();
  });
  await name(page).fill("連打CP");
  // All events run before React can re-render its disabled button.
  await name(page).evaluate(input => {
    const button = input.closest(".checkpoint-form")!.querySelector<HTMLButtonElement>(".primary-button")!;
    for (let i = 0; i < 5; i++) {
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      button.click();
    }
  });
  await expect(form(page).getByRole("button", { name: "追加中…", exact: true })).toBeDisabled();
  await name(page).press("Enter");
  expect(requests).toBe(1);
  release();
  await expect(form(page).getByRole("button", { name: "追加", exact: true })).toBeEnabled();
  expect(await references(page)).toHaveLength(0);
  await name(page).press("Enter");
  await expect(form(page)).toHaveCount(0);
  expect(requests).toBe(2);
  expect(await references(page)).toHaveLength(1);
  await expect(editor(page).getByText("連打CP", { exact: true })).toBeVisible();
});


for (const width of [390, 1100, 1440]) {
  test(`checkpoint MAP pick focuses once, reveals name and saves with Enter at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await form(page).getByRole("button", { name: "編集を閉じる", exact: true }).click();
    await page.getByRole("button", { name: "チェックポイントを追加", exact: true }).click();
    await expect(name(page)).not.toBeFocused();
    const route = page.getByRole("region", { name: "経路地図とLeg設定" });
    const map = route.locator(".route-map");
    for (const suffix of ["first", "second"]) {
      await map.click({ position: { x: 150, y: 150 } });
      await expect(name(page)).toBeFocused();
      await expect(name(page)).toBeInViewport({ ratio: 1 });
      await expect(route.locator(".checkpoint-draft-marker")).toHaveCount(1);
      await expect(form(page).getByLabel("緯度", { exact: true })).toHaveCount(0);
      await expect(form(page).getByLabel("経度", { exact: true })).toHaveCount(0);
      await expect(route.locator("#route-map-frame")).not.toHaveClass(/is-picking-checkpoint/);
      await page.keyboard.type(suffix);
      await expect(name(page)).toHaveValue(suffix === "first" ? "first" : "firstsecond");
      await page.keyboard.press("Tab");
      await expect(name(page)).not.toBeFocused();
      const otherControl = form(page).getByRole("button", { name: "編集を閉じる", exact: true });
      await otherControl.focus();
      await expect(otherControl).toBeFocused();
      await expect(name(page)).not.toBeFocused();
    }
    await form(page).getByRole("button", { name: "編集を閉じる", exact: true }).click();
    await expect(form(page)).toHaveCount(0);
    await expect(route.locator(".checkpoint-draft-marker")).toHaveCount(0);
    await page.getByRole("button", { name: "チェックポイントを追加", exact: true }).click();
    // Find a point on rendered route geometry for a valid real MAP pick,
    // instead of invoking application handlers or manually replacing coordinates.
    const segment = map.locator('path[stroke="#173b5e"]').first();
    await map.scrollIntoViewIfNeeded();
    const point = await segment.evaluate((element) => {
      const path = element as SVGPathElement;
      const point = path.getPointAtLength(path.getTotalLength() * 0.55);
      const screen = point.matrixTransform(path.getScreenCTM()!);
      return { x: screen.x, y: screen.y };
    });
    await page.mouse.click(point.x, point.y);
    await expect(name(page)).toBeFocused();
    await page.keyboard.type("MAP Enter CP");
    const leg = form(page).getByLabel("関連Leg");
    if (await leg.count()) await leg.selectOption({ index: 1 });
    await expect(form(page).getByRole("button", { name: "追加", exact: true })).toBeEnabled();
    // Re-pick the same point so typing and Enter follow the map focus without
    // any input focus operation, even when a Leg had to be explicitly selected.
    await map.scrollIntoViewIfNeeded();
    const again = await segment.evaluate((element) => {
      const path = element as SVGPathElement;
      const screen = path.getPointAtLength(path.getTotalLength() * 0.55).matrixTransform(path.getScreenCTM()!);
      return { x: screen.x, y: screen.y };
    });
    await page.mouse.click(again.x, again.y);
    await expect(name(page)).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(form(page)).toHaveCount(0);
    expect(await references(page)).toHaveLength(1);
    await expect(editor(page).getByText("MAP Enter CP", { exact: true })).toBeVisible();
    await expect(route.locator(".checkpoint-draft-marker")).toHaveCount(0);
    await editor(page).screenshot({ path: info.outputPath(`map-enter-${width}.png`) });
    expect(await page.pageErrors()).toEqual([]);
  });
}
