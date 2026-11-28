import { clickMapCoordinate } from "./helpers/mapCoordinate";
import { expectPlanningLayout } from "./helpers/planningLayout";
import { openProjectMenu } from "./helpers/header";
import { observeStartupProgress } from "./helpers/startupProgress";
import { test, artifactSessionKey } from "./helpers/localArtifact";
import { selectAirport } from "./helpers/mapCandidates";
import { enterImportWorkflow, expectImportedDraft, confirmImportedDraft } from "./helpers/importWorkflow";
import { expect, type Page } from "@playwright/test";
import { resolve } from "node:path";

const key = artifactSessionKey;
const isLocal = () => test.info().config.metadata.applicationMode === "local";
const snapshot = (page: Page) => page.evaluate(k => JSON.parse(sessionStorage.getItem(k)!), key);

test.beforeEach(async ({ context }) => {
  if (isLocal()) {
    await context.route("**/api/**", route => route.abort());
    await context.addInitScript(() => {
      const Original = Worker;
      (window as any).runtimeCount = 0;
      window.Worker = class extends Original {
        constructor(url: string | URL, options?: WorkerOptions) {
          super(url, options);
          (window as any).runtimeCount++;
        }
      };
    });
  }
});
async function open(page: Page) {
  await page.goto("/");
  await enterImportWorkflow(page);
  await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
}
async function imported(page: Page) {
  await open(page);
  await page.locator('#route-file').setInputFiles(resolve("../tests/fixtures/issue_43_golden.kml"));
  await expectImportedDraft(page);
}
async function confirmed(page: Page) {
  await imported(page);
  await confirmImportedDraft(page);
  await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
  await page.getByLabel("ETD JST", { exact: true }).fill("09:00");
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.getByLabel("地上風向 ° FROM").fill("360");
  await page.getByLabel("地上風速 kt").fill("15");
  await page.getByLabel("5,000 ft風向 ° FROM").fill("270");
  await page.getByLabel("5,000 ft風速 kt").fill("30");
  await expect(page.getByLabel("RJFM出発Legの計画高度", { exact: true })).toBeVisible();
}
async function calculated(page: Page) {
  await confirmed(page);
  for (const [name, altitude] of [["RJFM", "6500"], ["米ノ津", "7500"], ["玉名", "6500"]]) {
    await page.getByLabel(name + "出発Legの計画高度", { exact: true }).fill(altitude);
  }
  await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
  await expect(page.locator(".nav-log-table")).toBeVisible();
}
test("#564 #530 #422 deferred route confirmation during suspended assets", async ({ page, context }) => {
  test.skip(!isLocal(), "Local startup progress");
  await context.addInitScript(observeStartupProgress);
  await context.addInitScript(() => {
    (window as any).confirmRequests = 0;
    const original = Worker.prototype.postMessage;
    Worker.prototype.postMessage = function (message, ...options: any[]) {
      if (message.type === "APPLY" && message.argumentList?.[0]?.value === "confirmRoute") {
        (window as any).confirmRequests++;
      }
      return original.call(this, message, ...options);
    };
  });
  await open(page); // An empty same-tab session must still allow early input on reload.
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await context.route("**/local/data.zip", async route => { await pending; await route.continue(); });
  const assetsRequested = context.waitForEvent("request", { predicate: req => req.url().endsWith("/local/data.zip"), timeout: 120_000 });
  await page.reload({ waitUntil: "domcontentloaded" });
  const bar = page.getByRole("progressbar", { name: "準備の進み具合" });
  try {
    await assetsRequested;
    await expect(bar).toHaveCount(0);
    const originalViewport = page.viewportSize()!;
    for (const width of [390, 1100, 1280]) {
      await page.setViewportSize({ width, height: 850 });
      await expectPlanningLayout(page, width);
    }
    await page.setViewportSize(originalViewport);
    await selectAirport(page, "RJFM");
    const confirm = page.getByRole("button", { name: "経路を確定", exact: true });
    await expect(confirm).toBeDisabled();
    await clickMapCoordinate(page, 31.95, 131.5);
    await page.getByRole("button", { name: "2番目のWP1を削除" }).click();
    await expect(page.locator(".route-strip li")).toHaveCount(1);
    await clickMapCoordinate(page, 31.95, 131.5);
    await selectAirport(page, "RJFM");
    await expect(page.locator(".route-strip li")).toHaveCount(3);
    await expect(bar).toHaveCount(0);
    await expect(confirm).toBeEnabled();
    await confirm.evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
    await expect(confirm).toBeDisabled();
    await expect(bar).toBeVisible();
    await expect(page.getByRole("status")).toHaveText("計算用プログラムとデータを読み込んでいます");
    await expect(page.locator(".nav-log-table")).toHaveCount(0);
    const barBox = await bar.boundingBox(), stageBox = await page.getByRole("status").boundingBox();
    expect(stageBox!.y).toBeGreaterThanOrEqual(barBox!.y + barBox!.height);
  } finally { release(); }
  await enterImportWorkflow(page);
  await expect(bar).toHaveCount(0);
  await expect(page.getByLabel("DATE", { exact: true })).toBeVisible();
  const project = (await snapshot(page)).working.project;
  expect(project.route_nodes.map((node: { name: string }) => node.name)).toEqual(["RJFM", "WP1", "RJFM"]);
  expect(await page.evaluate(() => (window as any).confirmRequests)).toBe(1);
  const values = await page.evaluate(() => (window as unknown as { startupProgressValues: number[] }).startupProgressValues);
  expect(values.length).toBeGreaterThan(3);
  expect(values.at(-1)).toBe(100);
  expect(values.every((value, index) => value >= 0 && value <= 100 && (index === 0 || value >= values[index - 1]))).toBe(true);
  const frames = await page.evaluate(() => (window as any).startupProgressFrames as { percent: number; workspace: boolean }[]);
  expect(frames.some(frame => frame.percent === 100 && frame.workspace)).toBe(true);
});

test("#564 #530 ready route confirms without showing startup progress", async ({ page, context }) => {
  test.skip(!isLocal(), "Local startup progress");
  await context.addInitScript(observeStartupProgress);
  await open(page);
  await selectAirport(page, "RJFM");
  await clickMapCoordinate(page, 31.95, 131.5);
  await selectAirport(page, "RJFM");
  await page.evaluate(() => { (window as any).startupProgressValues.length = 0; });
  await page.getByRole("button", { name: "経路を確定", exact: true }).click();
  await expect(page.getByLabel("DATE", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as any).startupProgressValues)).toEqual([]);
});

test("#530 restoring a calculated session and starting another route keep both tabs independent", async ({ page, context }) => {
  test.skip(!isLocal(), "Local startup recovery");
  await calculated(page);
  const tas = page.locator(".nav-log-table").getByLabel(/手動TAS$/).first();
  const committedTas = await tas.inputValue();
  await tas.fill("999");
  const previous = await snapshot(page);
  let resume!: () => void;
  const paused = new Promise<void>(resolve => { resume = resolve; });
  await context.route("**/local/data.zip", async route => { await paused; await route.continue(); });
  await page.reload({ waitUntil: "domcontentloaded" });
  const opened = context.waitForEvent("page");
  await page.getByRole("link", { name: /別タブで新規経路/ }).click();
  const fresh = await opened;
  try {
    await selectAirport(fresh, "RJFM");
    await expect(fresh.locator(".route-strip li")).toHaveCount(1);
    await expect(page.locator(".nav-log-table")).toHaveCount(0);
    expect((await snapshot(page)).working).toEqual(previous.working);
  } finally { resume(); }
  await expect(tas).toHaveValue(committedTas);
  await enterImportWorkflow(fresh);
  expect((await snapshot(page)).working.last_calculation).toEqual(previous.working.last_calculation);
  await expect(fresh.locator(".route-strip li")).toContainText(["RJFM"]);
  expect((await snapshot(fresh)).working.project).toBeNull();
});

test("#355 startup reload replaces a failed Worker", async ({ page, context }) => {
  test.skip(!isLocal(), "Local Worker initialization failure");
  await context.addInitScript(() => {
    if (sessionStorage.getItem("issue355-worker-failed")) return;
    const Original = Worker;
    window.Worker = class extends Original {
      constructor(url: string | URL, options?: WorkerOptions) {
        super(url, options);
        sessionStorage.setItem("issue355-worker-failed", "1");
        (window as any).failStartup = () => this.dispatchEvent(new ErrorEvent("error", { message: "private Worker stack and token" }));
      }
    };
  });
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const requested = context.waitForEvent("request", { predicate: req => req.url().endsWith("/local/data.zip"), timeout: 120_000 });
  await context.route("**/local/data.zip", async route => { await pending; await route.continue(); }, { times: 1 });
  await page.goto("/");
  const confirm = page.getByRole("button", { name: "経路を確定", exact: true });
  try {
    await selectAirport(page, "RJFM");
    await selectAirport(page, "RJFM");
    await confirm.click();
    await expect(page.getByRole("progressbar")).toBeVisible();
    await requested;
    await page.evaluate(() => (window as any).failStartup());
    await expect(page.getByRole("alert").locator("code")).toHaveText("APPLICATION_UNAVAILABLE");
    await expect(page.getByRole("progressbar")).toHaveCount(0);
    await expect(confirm).toBeDisabled();
    await expect(confirm.locator("..").getByRole("button", { name: "起動を再試行" })).toBeVisible();
    await expect(page.locator("body")).not.toContainText("private Worker stack and token");
  } finally { release(); }
  const firstDocument = await page.evaluate(() => performance.timeOrigin);
  await page.getByRole("button", { name: "起動を再試行", exact: true }).click();
  await enterImportWorkflow(page);
  await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
  expect(await page.evaluate(() => performance.timeOrigin)).not.toBe(firstDocument);
  await expect(page.locator(".route-strip li")).toContainText(["RJFM", "RJFM"]);
  await expect(confirm).toBeEnabled();
});

test("#351 stale recovery permits recalculation with historical blockers and an unapplied pattern altitude", async ({ page }) => {
  await calculated(page);
  const before = await snapshot(page);
  await page.evaluate(k => {
    const saved = JSON.parse(sessionStorage.getItem(k)!);
    saved.working.outcome.issues = ["FLIGHT_PHASE_SEQUENCE_INVALID", "RJFM_INBOUND_DIRECT_DISTANCE_SHORTFALL"]
      .map(code => ({ code, severity: "BLOCKER", message: "historical", acknowledgement_required: false, metadata: {} }));
    saved.working.project.total_usable_fuel_gal = 75;
    saved.form.totalUsableFuelGal = "75";
    saved.form.destinationPatternAltitudeFtMsl = "1100";
    saved.calculationInputsAreLocallyCurrent = false;
    sessionStorage.setItem(k, JSON.stringify(saved));
  }, key);
  await page.reload();
  const pattern = page.getByLabel("今回採用する場周経路高度", { exact: true });
  const recalculate = page.getByRole("button", { name: "NAV LOGを再計算", exact: true });
  await expect(pattern).toHaveValue("1100");
  await expect(page.getByText("RECALCULATION_REQUIRED", { exact: true })).toBeVisible();
  await expect(page.locator(".status-rail").getByText("FLIGHT_PHASE_SEQUENCE_INVALID", { exact: true })).toHaveCount(0);
  await expect(recalculate).toBeEnabled();
  expect((await snapshot(page)).working.last_calculation).toEqual(before.working.last_calculation);

  // Invalid current input remains disabled with an existing, field-specific reason.
  await pattern.fill("123");
  await expect(pattern).toHaveAttribute("aria-invalid", "true");
  await expect(recalculate).toBeDisabled();
  await expect(page.getByText("100～25,000 ftの範囲で100 ft単位の整数を入力してください。")).toBeVisible();
  await page.reload();
  await expect(pattern).toHaveValue(String(before.working.project.metadata.ui_state.arrival_plan.selected_pattern_altitude_ft_msl));
  await expect(recalculate).toBeEnabled();
  expect((await snapshot(page)).working.last_calculation).toEqual(before.working.last_calculation);

  // Reload suppresses automatic calculation; a valid restored edit can be applied manually.
  await page.evaluate(k => {
    const saved = JSON.parse(sessionStorage.getItem(k)!);
    saved.form.destinationPatternAltitudeFtMsl = "1100";
    sessionStorage.setItem(k, JSON.stringify(saved));
  }, key);
  await page.reload();
  await expect(pattern).toHaveValue("1100");
  await expect(recalculate).toBeEnabled();
  await recalculate.click();
  await expect(page.getByText("RECALCULATION_REQUIRED", { exact: true })).toHaveCount(0);
  await expect(recalculate).toBeEnabled();
  const after = await snapshot(page);
  expect(after.working.project.metadata.ui_state.arrival_plan.selected_pattern_altitude_ft_msl).toBe(1100);
  expect(after.working.project.total_usable_fuel_gal).toBe(75);
  expect(after.working.last_calculation).not.toEqual(before.working.last_calculation);
  await page.reload();
  await expect(pattern).toHaveValue("1100");
  await expect(recalculate).toBeEnabled();
  expect((await snapshot(page)).working.last_calculation).toEqual(after.working.last_calculation);
});

test("#540 reload restores committed planning values, import and route selection", async ({ page }) => {
  await imported(page);
  const importedDraft = (await snapshot(page)).mapRouteDraft;
  await page.reload();
  await expectImportedDraft(page);
  expect((await snapshot(page)).mapRouteDraft).toEqual(importedDraft);
  expect((await snapshot(page)).working.project).toBeNull();
  await confirmImportedDraft(page);
  const before = await snapshot(page);
  const tgl = page.getByLabel("TGL", { exact: true });
  await page.evaluate(key => {
    const original = Storage.prototype.setItem;
    Object.assign(window, { sessionWrites: 0 });
    Storage.prototype.setItem = function(k, value) {
      if (k === key) (window as any).sessionWrites++;
      return original.call(this, k, value);
    };
  }, key);
  await tgl.fill("99");
  await expect(tgl).toHaveValue("99");
  expect(await page.evaluate(() => (window as any).sessionWrites)).toBe(0);
  await page.reload();
  await expect(tgl).toHaveValue(String(before.working.project.tgl_count));
  const altitude = page.getByLabel("RJFM出発Legの計画高度", { exact: true });
  const confirmedAltitude = await altitude.inputValue();
  await altitude.fill("123");
  await page.reload();
  await expect(altitude).toHaveValue(confirmedAltitude);
  expect((await snapshot(page)).working.project.id).toBe(before.working.project.id);
});

test("#540 JSON export stops if a required draft write fails", async ({ page }) => {
  test.skip(!isLocal(), "IndexedDB write failure");
  await calculated(page);
  const downloads: string[] = [];
  page.on("download", file => downloads.push(file.suggestedFilename()));
  await page.evaluate(() => {
    const put = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function(...args) {
      if (this.name === "projects") throw new DOMException("unavailable", "InvalidStateError");
      return put.apply(this, args);
    };
  });
  const tgl = page.getByLabel("TGL", { exact: true });
  await tgl.fill("2");
  const exportButton = page.getByRole("button", { name: "プロジェクトJSONをダウンロード" });
  await exportButton.click();
  await expect(page.getByRole("alert").filter({ hasText: "プロジェクトを自動保存できませんでした" }).first()).toBeVisible();
  await expect(exportButton).toBeEnabled();
  expect(downloads).toEqual([]);
  await expect(tgl).toHaveValue("2");
  expect((await snapshot(page)).working.project.tgl_count).not.toBe(2);
});

test("reload retains last-good and committed NAV LOG inputs without auto calculation", async ({ page }) => {
  await calculated(page);
  const before = await snapshot(page);
  const tas = page.locator(".nav-log-table").getByLabel(/手動TAS$/).first();
  const committedTas = await tas.inputValue();
  await tas.fill("999");
  await page.reload();
  await expect(page.locator(".nav-log-table")).toBeVisible();
  await expect(page.locator(".nav-log-table").getByLabel(/手動TAS$/).first()).toHaveValue(committedTas);
  expect((await snapshot(page)).working.outcome).toEqual(before.working.outcome);
  await page.waitForTimeout(1000); // exceeds both existing auto-recalculation debounces
  expect((await snapshot(page)).working.outcome).toEqual(before.working.outcome);
  await page.locator(".nav-log-table").getByLabel(/手動TAS$/).first().fill("120");
  await expect.poll(async () => (await snapshot(page)).working.outcome).not.toEqual(before.working.outcome);
});

test("new discards recovery; new tabs including opener clones never inherit work", async ({ page, context }) => {
  await confirmed(page);
  await page.getByLabel("TGL", { exact: true }).fill("3");
  const second = await context.newPage();
  await open(second);
  expect((await snapshot(second)).working.project).toBeNull();
  await confirmed(second);
  await second.getByLabel("TGL", { exact: true }).fill("7");
  const popupPromise = page.waitForEvent("popup");
  await page.evaluate(() => window.open(location.href, "_blank"));
  const popup = await popupPromise;
  await enterImportWorkflow(popup);
  await expect(popup.getByLabel("TGL", { exact: true })).toHaveCount(0);
  expect((await snapshot(popup)).form.tglCount).toBe("0");
  expect((await snapshot(popup)).working.project).toBeNull();
  await popup.close();
  await expect.poll(async () => (await snapshot(second)).working.project.tgl_count).toBe(7);
  await second.reload();
  await expect(second.getByLabel("TGL", { exact: true })).toHaveValue("7");
  await page.reload();
  await expect(page.getByLabel("TGL", { exact: true })).toHaveValue("3");
  // Cancel preserves current inputs; accepting repeatedly resets UI and Python work,
  // but neither reloads the document nor creates another same-account runtime.
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "新規", exact: true }).click();
  await expect(page.getByLabel("TGL", { exact: true })).toHaveValue("3");
  const runtimeCount = await page.evaluate(() => (window as any).runtimeCount);
  if (isLocal()) await page.evaluate(() => { (window as any).sameWorkDocument = true; });
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt === 0) page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "新規", exact: true }).click();
    await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "KML/KMZから開始", exact: true })).toHaveCount(0);
    await expect.poll(async () => (await snapshot(page))?.form.tglCount).toBe("0");
    expect((await snapshot(page)).working.project).toBeNull();
    expect((await snapshot(page)).form.weatherMode).toBe("FORECAST");
    if (isLocal()) {
      expect(await page.evaluate(() => (window as any).sameWorkDocument)).toBe(true);
      expect(await page.evaluate(() => (window as any).runtimeCount)).toBe(runtimeCount);
    }
  }
  await page.reload();
  expect((await snapshot(page)).working.project).toBeNull();
  await expect(second.getByLabel("TGL", { exact: true })).toHaveValue("7");
});

for (const corruption of ["json", "version", "working"]) {
  test("corrupt recovery starts safely: " + corruption, async ({ page }) => {
    await confirmed(page);
    await page.evaluate(({ key, corruption }) => {
      const saved = JSON.parse(sessionStorage.getItem(key)!);
      if (corruption === "version") saved.version = 99;
      if (corruption === "working") saved.working.project = { broken: true };
      sessionStorage.setItem(key, corruption === "json" ? "{" : JSON.stringify(saved));
    }, { key, corruption });
    await page.reload();
    await expect(page.locator("#app-notification-region").getByText("前回の作業を復元できなかったため、新規作業を開始しました。", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
    expect((await snapshot(page)).working.project).toBeNull();
    expect((await snapshot(page)).form.weatherMode).toBe("FORECAST");
  });
}

test("calculation interrupted by reload is not resent and late result cannot replace restored work", async ({ page }) => {
  await calculated(page);
  const previous = await snapshot(page);
  let calculations = 0;
  if (isLocal()) {
    await page.evaluate(() => {
      const Original = Worker.prototype.postMessage;
      Worker.prototype.postMessage = function(message: any, ...rest: any[]) {
        if (message.type === "APPLY" && message.argumentList?.[0]?.value === "calculate") {
          (window as any).heldCalculation = true;
          return;
        }
        return (Original as any).call(this, message, ...rest);
      };
    });
  } else {
    await page.route("**/api/calculation-jobs", async route => {
      calculations++;
      await route.fulfill({ json: { job_id: "held", status: "calculating", progress_percent: 1, progress_message: "held" } });
    });
    await page.route("**/api/calculation-jobs/held", async route => {
      await route.fulfill({ json: { job_id: "held", status: "calculating", progress_percent: 1, progress_message: "held" } });
    });
  }
  await page.getByLabel("TGL", { exact: true }).fill("2");
  await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
  await expect(page.locator(".calculation-progress-backdrop")).toBeVisible();
  const overlay = page.getByRole("status", { name: "NAV LOGを計算中" });
  if (!isLocal()) {
    await expect.poll(() => calculations).toBe(1);
    await expect(overlay.getByRole("progressbar", { name: "NAV LOGを計算中 1%" })).toHaveAttribute("value", "1");
  } else {
    await page.waitForFunction(() => (window as any).heldCalculation);
    await expect(overlay.getByRole("progressbar")).toHaveAttribute("value", "20");
  }
  const interrupted = await snapshot(page);
  expect(interrupted.working.outcome.summary).toEqual(previous.working.outcome.summary);
  await page.reload();
  await expect(page.locator(".nav-log-table")).toBeVisible();
  await expect(page.getByLabel("TGL", { exact: true })).toHaveValue("2");
  await page.waitForTimeout(1200);
  expect((await snapshot(page)).working.outcome).toEqual(interrupted.working.outcome);
  await expect(page.locator(".calculation-progress-backdrop")).toHaveCount(0);
  if (!isLocal()) expect(calculations).toBe(1);
});

test("KMZ document choice resumes after reload with modal closed", async ({ page }) => {
  const { execFileSync } = await import("node:child_process");
  const bytes = execFileSync("python3", ["-c",
    "import io,zipfile,sys; b=io.BytesIO(); z=zipfile.ZipFile(b,'w'); s=open('../tests/fixtures/issue_43_golden.kml').read(); z.writestr('a.kml',s); z.writestr('b.kml',s); z.close(); sys.stdout.buffer.write(b.getvalue())"]);
  await open(page);
  await page.locator('#route-file').setInputFiles({ name: "routes.kmz", mimeType: "application/vnd.google-earth.kmz", buffer: bytes });
  await expect(page.locator('#route-file')).toBeEnabled();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByLabel("KML文書").selectOption("b.kml");
  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "KMZからの選択を続ける" }).click();
  await expect(page.getByLabel("KML文書")).toHaveValue("b.kml");
  await page.getByRole("button", { name: "選択したKMLを読み込む" }).click();
  await confirmImportedDraft(page);
  await page.getByLabel("FUEL gal", { exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("TGL", { exact: true })).toBeFocused();
});

test("restored Check Point and VOR input remains editable; workflow positions are preserved", async ({ page }) => {
  await calculated(page);
  await page.getByLabel("VOR基準局", { exact: true }).selectOption({ index: 2 });
  const vor = await page.getByLabel("VOR基準局", { exact: true }).inputValue();
  await page.getByRole("button", { name: "チェックポイントを追加", exact: true }).click();
    await clickMapCoordinate(page, 32.0, 130.9);
  await page.locator(".checkpoint-form").getByLabel("名称", { exact: true }).fill("未確定地点");
  await expect.poll(async () => (await snapshot(page)).checkPointDraft.latitude).not.toBe("");
  expect((await snapshot(page)).checkPointDraft.name).toBe("");
  const pendingCheckPoint = (await snapshot(page)).checkPointDraft;
  await page.reload();
  await expect(page.locator(".nav-log-table")).toBeVisible();
  await expect(page.getByLabel("VOR基準局", { exact: true })).toHaveValue(vor);
  await expect(page.locator(".checkpoint-form")).toHaveCount(0);
  await page.getByRole("button", { name: "チェックポイントの編集を続ける" }).click();
  await expect(page.locator(".checkpoint-form").getByLabel("名称", { exact: true })).toHaveValue("");
  expect((await snapshot(page)).checkPointDraft).toEqual(pendingCheckPoint);
  await expect(page.locator(".checkpoint-form").getByLabel("緯度", { exact: true })).toHaveCount(0);
  for (const width of [1100, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    const boxes = await Promise.all([".input-rail", ".route-workspace", ".status-rail", ".nav-log-scroll"]
      .map(selector => page.locator(selector).boundingBox()));
    expect(boxes.every(Boolean)).toBe(true);
    await expectPlanningLayout(page, width);
  }
});

test("#540 late autosave after restore updates weather status and preserves newer invalid input", async ({ page }) => {
  await imported(page);
  await confirmImportedDraft(page);
  await page.reload();
  await expect(page.getByLabel("TGL", { exact: true })).toBeVisible();
  const pattern = page.getByLabel("今回採用する場周経路高度", { exact: true });
  const vrep = page.getByLabel(/のVREP通過高度$/);
  const initialVrep = Number(await vrep.inputValue());
  const initialPattern = Number(await pattern.inputValue());
  let release!: () => void;
  let held = false;
  if (isLocal()) {
    await page.evaluate(() => {
      const original = Worker.prototype.postMessage;
      Worker.prototype.postMessage = function(message: any, ...rest: any[]) {
        if (message.type === "APPLY" && message.argumentList?.[0]?.value === "updateProject") {
          Worker.prototype.postMessage = original;
          (window as any).releaseAutosave = () => (original as any).call(this, message, ...rest);
          return;
        }
        return (original as any).call(this, message, ...rest);
      };
    });
  } else {
    const gate = new Promise<void>(resolve => { release = resolve; });
    await page.route("**/api/project", async route => {
      if (held) return route.continue();
      held = true;
      const response = await route.fetch();
      await gate;
      await route.fulfill({ response });
    });
  }
  await pattern.fill(String(initialPattern + 200));
  await page.getByLabel("気象モード").selectOption("FTD");
  if (isLocal()) await page.waitForFunction(() => Boolean((window as any).releaseAutosave));
  else await expect.poll(() => held).toBe(true);
  await page.getByLabel("TGL", { exact: true }).fill("99");
  if (isLocal()) await page.evaluate(() => (window as any).releaseAutosave());
  else release();
  await expect(page.locator("#readiness-details .provenance-list dd").first()).toHaveText("FTD固定気象");
  await expect(vrep).toHaveValue(String(initialVrep + 200));
  await expect(page.getByLabel("TGL", { exact: true })).toHaveValue("99");
  await page.reload();
  await expect(page.getByLabel("TGL", { exact: true })).toHaveValue("0");
  await expect(page.getByLabel("気象モード")).toHaveValue("FTD");
  await page.getByLabel("TGL", { exact: true }).fill("3");
  await expect.poll(async () => (await snapshot(page)).working.project.tgl_count).toBe(3);
});

test("new reports storage refusal before disposing the working runtime", async ({ page }) => {
  await confirmed(page);
  const before = await snapshot(page);
  await page.evaluate(() => {
    const original = Storage.prototype.removeItem;
    Storage.prototype.removeItem = function(key) {
      if (key === "autonavlog.working-session.v1") throw new DOMException("denied", "SecurityError");
      return original.call(this, key);
    };
  });
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "新規", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("作業状態を破棄できませんでした");
  expect((await snapshot(page)).working.project.id).toBe(before.working.project.id);
  await page.getByLabel("TGL", { exact: true }).fill("4");
  await expect.poll(async () => (await snapshot(page)).working.project.tgl_count).toBe(4);
});

test("unsubmitted pasted KML stays in the current screen", async ({ page }) => {
  await open(page);
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", {
    configurable: true, value: { readText: async () => { throw new Error("denied"); } },
  }));
  await page.getByRole("button", { name: "Google Earth からペースト", exact: true }).click();
  await page.getByRole("dialog").getByRole("textbox").fill("<kml>入力途中");
  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "貼り付けたKMLの編集を続ける" })).toHaveCount(0);
});

for (const width of [1100, 1440]) {
  test(`confirmed route draft reload, cancel and reconfirm at ${width}px`, async ({ page }) => {
    test.setTimeout(360_000);
    await page.setViewportSize({ width, height: 1100 });
    await calculated(page);
    await page.getByRole("button", { name: "経路を編集", exact: true }).click();
    const strip = page.getByRole("list", { name: "経路リスト" });
    await expect(strip).toBeVisible();
    const before = await snapshot(page);
    const count = before.mapRouteDraft.length;
    const input = (await page.locator(".input-rail").boundingBox())!;
    const route = (await page.locator(".route-workspace").boundingBox())!;
    await expectPlanningLayout(page, width);
    expect((await page.locator(".route-map").boundingBox())!.height).toBeGreaterThanOrEqual(300);
    await expect(page.locator(".nav-log-table")).toBeVisible();
    await expect(page.getByRole("button", { name: "KML/KMZから開始", exact: true })).toHaveCount(0);
    await strip.locator("li").nth(1).getByRole("button").click();
    expect((await snapshot(page)).working.project).toEqual(before.working.project);
    await page.reload();
    await expect(strip.locator("li")).toHaveCount(count - 1);
    expect((await snapshot(page)).working.last_calculation).toEqual(before.working.last_calculation);
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "キャンセル", exact: true }).click();
    await expect(strip).toHaveCount(0);
    expect((await snapshot(page)).working.project).toEqual(before.working.project);
    await page.getByRole("button", { name: "経路を編集", exact: true }).click();
    await expect(strip.locator("li")).toHaveCount(count);
    await strip.locator("li").nth(1).getByRole("button").click();
    await page.getByRole("button", { name: "経路を確定", exact: true }).click();
    await expect(strip).toHaveCount(0);
    await expect.poll(async () => (await snapshot(page)).working.project.route_nodes.length).toBe(count - 1);
    expect((await snapshot(page)).working.project.id).toBe(before.working.project.id);
  });
}


test("confirmed route extension relocates arrival phases and preserves retained inputs", async ({ page }) => {
  test.setTimeout(360_000);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await calculated(page);
  const before = (await snapshot(page)).working;
  await page.getByRole("button", { name: "経路を編集", exact: true }).click();
  await expect(page.getByRole("list", { name: "経路リスト" })).toBeVisible();
  await selectAirport(page, "RJFK");
  await page.getByRole("button", { name: "経路を確定", exact: true }).click();
  await expect(page.getByRole("list", { name: "経路リスト" })).toHaveCount(0);
  const after = (await snapshot(page)).working;
  expect(after.project.sections.map((section: any) => section.phase)).toEqual([
    "CLIMB", "CRUISE", "CRUISE", "DESCENT", "VISUAL_ARRIVAL",
  ]);
  for (let i = 0; i < before.project.sections.length; i++) {
    expect(after.project.sections[i].id).toBe(before.project.sections[i].id);
    expect(after.project.sections[i].planned_altitude_ft_msl).toBe(before.project.sections[i].planned_altitude_ft_msl);
  }
  expect(after.last_calculation).toEqual(before.last_calculation);
});


for (const draftKind of ["map", "import", "unmatched import", "multiple unmatched import"] as const) {
  test(`deleting another saved Project preserves the new ${draftKind} Draft`, async ({ page }) => {
    await confirmed(page);
    await openProjectMenu(page);
    await page.getByLabel("プロジェクト", { exact: true }).fill("Saved route");
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await expect(page.getByText("プロジェクトを保存しました。", { exact: true })).toBeVisible();
    const savedId = (await snapshot(page)).working.project.id;
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "新規", exact: true }).click();
    await expect(page.getByRole("heading", { name: "経路作成", exact: true })).toBeVisible();
    if (draftKind === "map") {
      await selectAirport(page, "RJFM");
      await selectAirport(page, "RJFO");
    } else if (draftKind === "import") {
      await page.locator('#route-file').setInputFiles(resolve("../tests/fixtures/issue_43_golden.kml"));
      await expectImportedDraft(page);
    } else {
      await page.locator('#route-file').setInputFiles({
        name: "unmatched.kml", mimeType: "application/vnd.google-earth.kml+xml",
        buffer: Buffer.from('<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><LineString><coordinates>140,40,0 131.2,32,0 130.7194,31.8034,0</coordinates></LineString></Placemark>'
          + (draftKind === "multiple unmatched import" ? '<Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>131.4486,31.8772,0 131.2,32,0 130.7194,31.8034,0 131.4486,31.8772,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>' : '')
          + '</Document></kml>'),
      });
      if (draftKind === "multiple unmatched import") {
        const choice = page.getByRole("dialog", { name: "経路選択", exact: true });
        await choice.getByRole("combobox").selectOption("line:0");
        await choice.getByRole("button", { name: "KMLを取り込む", exact: true }).click();
        await expect(choice).toBeHidden();
      }
      await expect(page.getByRole("alert")).toContainText("KML始点から5 NM以内");
    }
    const strip = page.getByRole("list", { name: "経路リスト" });
    await expect(strip).toBeVisible();
    const points = await strip.locator("li").allTextContents();
    const before = await snapshot(page);
    expect(before.working.project).toBeNull();
    if (draftKind.includes("unmatched")) {
      expect(before.pendingImportDraft).toBe(true);
      await expect(page.getByRole("button", { name: "経路を確定", exact: true })).toBeDisabled();
    }
    await openProjectMenu(page);
    await page.getByLabel("保存済み", { exact: true }).selectOption(savedId);
    const confirmations: string[] = [];
    page.on("dialog", dialog => { confirmations.push(dialog.message()); void dialog.accept(); });
    await openProjectMenu(page);
    await page.getByRole("button", { name: "保存済みプロジェクトを削除", exact: true }).click();
    await expect(page.getByLabel("保存済み", { exact: true }).locator(`option[value="${savedId}"]`)).toHaveCount(0);
    expect(confirmations).toHaveLength(1);
    expect(confirmations[0]).toContain("保存済みプロジェクト");
    await expect(page.getByRole("dialog", { name: "経路選択", exact: true })).toHaveCount(0);
    await expect(strip.locator("li")).toHaveText(points);
    expect((await snapshot(page)).form.candidateKey).toBe(before.form.candidateKey);
    for (const field of ["mapRouteDraft", "pendingImportDraft", "selectedImportCandidate", "editingRouteProjectId"]) {
      expect((await snapshot(page))[field]).toEqual(before[field]);
    }
    await page.reload();
    await expect(strip.locator("li")).toHaveText(points);
    expect((await snapshot(page)).working.project).toBeNull();
    expect((await snapshot(page)).mapRouteDraft).toEqual(before.mapRouteDraft);
    expect((await snapshot(page)).pendingImportDraft).toEqual(before.pendingImportDraft);
    expect((await snapshot(page)).form.candidateKey).toBe(before.form.candidateKey);
    await expect(page.getByRole("dialog", { name: "経路選択", exact: true })).toHaveCount(0);
    if (draftKind.includes("unmatched")) {
      await expect(page.getByRole("button", { name: "経路を確定", exact: true })).toBeDisabled();
    }
  });
}
