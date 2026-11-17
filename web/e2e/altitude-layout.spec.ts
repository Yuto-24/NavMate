import { expect, test, type Locator, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";

async function importRoute(page: Page, fixture: string) {
  await page.goto("/");
  await enterImportWorkflow(page);
  await page.locator('input[type="file"]').setInputFiles(fileURLToPath(new URL(`../../tests/fixtures/${fixture}`, import.meta.url)));
  await confirmImportedDraft(page);
  await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.getByLabel("地上風向 ° FROM").fill("360");
  await page.getByLabel("地上風速 kt").fill("15");
  await page.getByLabel("5,000 ft風向 ° FROM").fill("270");
  await page.getByLabel("5,000 ft風速 kt").fill("30");
  await page.getByLabel("ETD JST", { exact: true }).fill("09:00");
  await expect(page.locator(".timeline-stop:last-child")).toBeVisible();
}

async function importInboundRoute(page: Page) {
  await importRoute(page, "altitude_inbound_compact.kml");
  // Main generates WP names and defaults RJFO to VOR Tracking. Recreate the
  // accepted airport-origin route through its existing planning controls.
  await expect(page.getByRole("checkbox", { name: "VOR Tracking Mode", exact: true })).toBeChecked();
  await page.getByRole("checkbox", { name: "VOR Tracking Mode", exact: true }).uncheck();
  await expect(page.locator(".route-point-content strong").first()).toHaveText("RJFO");
  for (const [index, name] of [[1, "鶴御崎"], [4, "有田"]] as const) {
    const point = page.locator(".timeline-stop").nth(index);
    await point.locator(".route-name-edit").click();
    await point.locator(".route-name-editor input").fill(name);
    await point.locator(".route-name-save").click();
    await expect(point.locator("strong")).toHaveText(name);
  }
}

async function assertIntervalRows(page: Page) {
  const points = page.locator(".route-timeline .route-point-content");
  const legs = page.locator(".timeline-leg");
  expect(await points.count()).toBeGreaterThan(2);
  await expect(legs).toHaveCount(await points.count() - 1);
  for (const leg of await legs.all()) {
    const g = await leg.evaluate(element => {
      const rect = (e: Element) => { const b=e.getBoundingClientRect(); return {top:b.top,bottom:b.bottom,left:b.left,right:b.right}; };
      const from=document.getElementById(`route-point-${element.getAttribute("data-from-node-id")}`)!;
      const to=document.getElementById(`route-point-${element.getAttribute("data-to-node-id")}`)!;
      return {leg:rect(element),from:rect(from.closest(".timeline-node")!),to:rect(to.closest(".timeline-node")!),controls:[...element.querySelectorAll("input,select,.route-phase-primary,.descent-rate-result")].filter(control => control.getClientRects().length > 0).map(rect)};
    });
    expect(g.leg.top).toBeGreaterThanOrEqual(g.from.bottom - 1);
    expect(g.leg.bottom).toBeLessThanOrEqual(g.to.top + 1);
    for(const c of g.controls) { expect(c.top).toBeGreaterThanOrEqual(g.leg.top); expect(c.bottom).toBeLessThanOrEqual(g.leg.bottom + 1); }
  }
  const arrival=page.locator(".timeline-stop").last();
  await expect(arrival.locator(".arrival-altitude-control")).toHaveCount(1);
  await expect(arrival.locator(".phase-arrival-value")).toHaveCount(1);
  await expect(arrival.locator(".timeline-leg")).toHaveCount(0);
}

async function assertWorkflowOrder(page: Page, width: number) {
  const boxes=await page.evaluate(() => [".map-frame",".planning-pane",".nav-log-focus-target"].map(selector=>{const r=document.querySelector(selector)!.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};}));
  if(width<=700) expect(boxes[1]!.y).toBeGreaterThanOrEqual(boxes[0]!.y+boxes[0]!.height-1);
  else { expect(boxes[1]!.x).toBeGreaterThanOrEqual(boxes[0]!.x+boxes[0]!.width-1);expect(Math.abs(boxes[0]!.y-boxes[1]!.y)).toBeLessThanOrEqual(1); }
  expect(boxes[2]!.y).toBeGreaterThanOrEqual(Math.max(...boxes.slice(0,2).map(b=>b.y+b.height))-1);
  for(const guide of await page.locator(".rjfm-inbound-guidance").all()) {const b=(await guide.boundingBox())!;expect(b.y).toBeGreaterThanOrEqual(boxes[2]!.y+boxes[2]!.height-1);}
}

async function selectFirstCandidate(row: Locator) {
  const select = row.locator(".altitude-candidate-select");
  const value = await select.locator("option").first().getAttribute("value");
  expect(value).not.toBeNull();
  await select.selectOption(value!);
  await expect(select).toHaveValue(value!);
  await expect(row.locator(".table-number-input")).toHaveCount(0);
}

async function assertFitsContainer(page: Page) {
  const layout=await page.locator(".route-timeline").evaluate(element=>({width:element.clientWidth,scroll:element.scrollWidth,controls:[...element.querySelectorAll("input,select,button,.fixed-altitude-control,.arrival-altitude-control")].map(control=>{const b=control.getBoundingClientRect(),p=element.getBoundingClientRect();return {left:b.left,right:b.right,min:p.left,max:p.right};})}));
  expect(layout.scroll).toBeLessThanOrEqual(layout.width+1);
  for(const c of layout.controls){expect(c.left).toBeGreaterThanOrEqual(c.min);expect(c.right).toBeLessThanOrEqual(c.max+1);}
}

for (const containerWidth of [600, 390]) {
  test(`inbound table fits an actual ${containerWidth}px container during edits`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1100, height: 1000 });
    await importInboundRoute(page);
    await page.getByRole("button", { name: "メッセージを閉じる" }).click();
    await page.locator(".route-timeline").evaluate((element, width) => { element.style.width = `${width}px`; }, containerWidth);
    await expect(page.getByText("本アプリは地表高を判定しないため、候補外の値は違法判定ではなく要確認表示です。", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("OMARU出発Legの固定高度")).toContainText("4,500 ft 固定");
    await expect(page.getByLabel("有田のVREP通過高度", { exact: true })).toHaveValue("1500");
    await expect(page.locator(".arrival-airport-reference")).toContainText("19 ft MSL");
    await expect(page.getByLabel("今回採用する場周経路高度", { exact: true })).toHaveValue("1000");
    await assertFitsContainer(page);
    await assertIntervalRows(page);
    await page.locator(".route-timeline").screenshot({ path: testInfo.outputPath(`inbound-container-${containerWidth}.png`) });

    const row = page.locator(".timeline-leg").filter({ has: page.locator(".altitude-candidate-select") }).first();
    const others = page.locator(".timeline-leg .table-number-input");
    const before = await others.evaluateAll(inputs => inputs.map(input => (input as HTMLInputElement).value));
    for (const value of ["3000", "", "4400"]) {
      await row.locator(".table-number-input").fill(value);
      await expect(row.locator(".table-number-input")).toHaveValue(value);
      await assertFitsContainer(page);
      await assertIntervalRows(page);
    }
    await expect(row.locator(".field-error")).toContainText("候補外（警告）");
    expect((await others.evaluateAll(inputs => inputs.map(input => (input as HTMLInputElement).value))).slice(1)).toEqual(before.slice(1));
    const point = page.locator(".timeline-stop").filter({ has: page.locator(".route-name-edit, .route-name-editor") }).first();
    await point.locator(".route-name-edit").click();
    await point.locator(".route-name-editor input").fill(" ");
    await point.locator(".route-name-save").click();
    await expect(point.locator(".field-error")).toBeVisible();
    await assertFitsContainer(page);
    await assertIntervalRows(page);
    await point.locator(".route-name-editor input").fill("長い経路点名称を折り返して区間高度の位置を確認する地点");
    await point.locator(".route-name-save").click();
    await expect(point.locator(".route-name-editor")).toHaveCount(0);
    await assertFitsContainer(page);
    await assertIntervalRows(page);
    await page.getByLabel("今回採用する場周経路高度", { exact: true }).fill("50");
    await expect(page.locator(".arrival-altitude-help.field-error")).toBeVisible();
    await page.locator(".phase-edit-toggle").click();
    await assertFitsContainer(page);
    await assertIntervalRows(page);
    await page.locator(".route-timeline").screenshot({ path: testInfo.outputPath(`inbound-container-${containerWidth}-warnings.png`) });
    await selectFirstCandidate(row);
    await expect(row.locator(".altitude-warning-cell")).toHaveCount(0);
    await page.getByLabel("今回採用する場周経路高度", { exact: true }).fill("1000");
    await assertFitsContainer(page);
    await assertIntervalRows(page);
  });
}

test("inbound timeline keeps point and leg ownership distinct", async ({ page }) => {
  await page.setViewportSize({width:820,height:1000});
  await importInboundRoute(page);
  await expect(page.locator(".route-point-content strong")).toHaveText(["RJFO","鶴御崎","OMARU","UMK","有田","RJFM"]);
  await assertIntervalRows(page);
  await assertFitsContainer(page);
});

test("route editing hides ALT controls and cancelling preserves the planning intervals", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 1000 });
  await importInboundRoute(page);
  await page.getByLabel("RJFO出発Legの計画高度", { exact: true }).fill("4400");
  await page.locator(".phase-edit-toggle").click();
  await expect(page.locator(".phase-edit-note")).toBeVisible();
  const before = await page.locator(".timeline-leg .table-number-input")
    .evaluateAll(inputs => inputs.map(input => (input as HTMLInputElement).value));
  await page.getByRole("button", { name: "経路を編集", exact: true }).click();
  await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
  await expect(page.locator(".route-timeline")).toHaveCount(0);
  await expect(page.locator(".phase-edit-note")).toHaveCount(0);
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "キャンセル", exact: true }).click();
  await expect(page.locator(".timeline-stop:last-child")).toBeVisible();
  await expect(page.locator(".route-point-content strong"))
    .toHaveText(["RJFO", "鶴御崎", "OMARU", "UMK", "有田", "RJFM"]);
  expect(await page.locator(".timeline-leg .table-number-input")
    .evaluateAll(inputs => inputs.map(input => (input as HTMLInputElement).value))).toEqual(before);
  await expect(page.getByRole("checkbox", { name: "VOR Tracking Mode", exact: true })).not.toBeChecked();
  await expect(page.getByLabel("OMARU出発Legの固定高度")).toContainText("4,500 ft 固定");
  await assertIntervalRows(page);
});

for (const width of [390, 1100, 1440]) {
  test(`altitude controls stay between endpoints with warnings and calculated descent at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await importRoute(page, "issue_43_golden.kml");
    await assertIntervalRows(page);
    const candidateRow = page.locator(".timeline-leg").filter({ has: page.locator(".altitude-candidate-select") }).first();
    await candidateRow.locator(".table-number-input").fill("4400");
    await expect(candidateRow.locator(".altitude-warning-cell")).toBeVisible();
    await expect(candidateRow.locator(".field-error")).toContainText("候補外（警告）");
    await assertIntervalRows(page);
    // Repeated raw edits keep the same section and neighbouring input values.
    const neighbours = page.locator(".timeline-leg .table-number-input");
    const before = await neighbours.evaluateAll(inputs => inputs.map(input => (input as HTMLInputElement).value));
    for (const value of ["", "4600", "4400"]) {
      await candidateRow.locator(".table-number-input").fill(value);
      await expect(candidateRow.locator(".table-number-input")).toHaveValue(value);
      await assertIntervalRows(page);
    }
    expect((await neighbours.evaluateAll(inputs => inputs.map(input => (input as HTMLInputElement).value))).slice(1)).toEqual(before.slice(1));
    await selectFirstCandidate(candidateRow);
    await expect(candidateRow.locator(".altitude-warning-cell")).toHaveCount(0);
    await expect(candidateRow.locator(".custom-altitude-warning")).toHaveCount(0);
    await candidateRow.locator(".altitude-candidate-select").selectOption("custom");
    await expect(candidateRow.locator(".custom-altitude-warning")).toBeVisible();
    await expect(candidateRow.locator(".field-error")).toHaveCount(0);
    await candidateRow.locator(".table-number-input").fill("4400");
    await expect(candidateRow.locator(".field-error")).toContainText("候補外（警告）");
    await expect(candidateRow.locator(".custom-altitude-warning")).toHaveCount(0);
    await selectFirstCandidate(candidateRow);
    await assertIntervalRows(page);

    const editablePoint = page.locator(".timeline-stop").filter({ has: page.locator(".route-name-edit, .route-name-editor") }).first();
    await editablePoint.locator(".route-name-edit").click();
    await editablePoint.locator(".route-name-editor input").fill(" ");
    await editablePoint.locator(".route-name-save").click();
    await expect(editablePoint.locator(".field-error")).toBeVisible();
    await assertIntervalRows(page);
    await editablePoint.locator(".route-name-cancel").click();
    // A saved long name changes natural row height without changing leg ownership.
    const originalName = await editablePoint.locator("strong").innerText();
    await editablePoint.locator(".route-name-edit").click();
    await editablePoint.locator(".route-name-editor input").fill("長い経路点名称を折り返して区間高度の位置を確認する地点");
    await editablePoint.locator(".route-name-save").click();
    await expect(editablePoint.locator(".route-name-editor")).toHaveCount(0);
    await assertIntervalRows(page);

    await editablePoint.locator(".route-name-edit").click();
    await editablePoint.locator(".route-name-editor input").fill(originalName);
    await editablePoint.locator(".route-name-save").click();
    await expect(editablePoint.locator("strong")).toHaveText(originalName);

    for (const [name, altitude] of [["RJFM", "6500"], ["米ノ津", "7500"], ["玉名", "6500"]]) {
      const input = page.getByLabel(`${name}出発Legの計画高度`, { exact: true });
      if (!(await input.count())) await page.locator(".timeline-stop").filter({ has: page.locator(".route-name-display strong", { hasText: new RegExp(`^${name}$`) }) }).locator(".altitude-candidate-select").selectOption("custom");
      await input.fill(altitude);
    }
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    await expect(page.locator(".nav-log-table")).toBeVisible();
    await expect(page.locator(".descent-rate-result")).toBeVisible();
    await assertIntervalRows(page);
    await assertWorkflowOrder(page, width);
    await page.locator(".route-timeline").screenshot({ path: testInfo.outputPath(`altitude-interval-${width}.png`) });
  });

  test(`fixed and arrival altitude details stay within their rows at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await importRoute(page, "issue_129_omaru_point.kml");
    await expect(page.locator(".fixed-altitude-control").first()).toBeVisible();
    await expect(page.locator(".timeline-node.has-node-altitude")).toHaveCount(2);
    await assertIntervalRows(page);
    const arrival = page.locator(".arrival-altitude-control");
    await expect(arrival.locator(".arrival-airport-reference")).toBeVisible();
    await page.getByLabel("今回採用する場周経路高度", { exact: true }).fill("50");
    await expect(arrival.locator(".field-error")).toBeVisible();
    await assertIntervalRows(page);
    await page.getByLabel("今回採用する場周経路高度", { exact: true }).fill("1300");
    await expect(page.getByLabel("今回採用する場周経路高度", { exact: true })).toHaveValue("1300");
    await expect(arrival.locator(".field-error")).toHaveCount(0);
    await assertIntervalRows(page);
    await page.locator(".route-timeline").screenshot({ path: testInfo.outputPath(`altitude-fixed-arrival-${width}.png`) });
  });
}
