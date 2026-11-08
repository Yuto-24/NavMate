import { test, expect, type Page } from "@playwright/test";
import { resolve } from "node:path";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";

async function create(page: Page, name: string, calculate = false) {
  await enterImportWorkflow(page);
  await page.locator('input[type="file"]').setInputFiles(resolve("../tests/fixtures/issue_43_golden.kml"));
  await confirmImportedDraft(page);
  await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.getByLabel("ETD JST", { exact: true }).fill("09:00");
  if (calculate) {
    await page.getByLabel("地上風向 ° FROM").fill("360");
    await page.getByLabel("地上風速 kt").fill("15");
    await page.getByLabel("5,000 ft風向 ° FROM").fill("270");
    await page.getByLabel("5,000 ft風速 kt").fill("30");
    for (const [point, altitude] of [["RJFM", "6500"], ["米ノ津", "7500"], ["玉名", "6500"]]) {
      await page.getByLabel(`${point}出発Legの計画高度`, { exact: true }).fill(altitude!);
    }
    await page.getByRole("button", { name: /NAV LOGを(?:作る|再計算)$/ }).click();
    await expect(page.locator(".nav-log-table")).toBeVisible();
  }
  await page.getByLabel("プロジェクト", { exact: true }).fill(name);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
}
async function load(page: Page, id: string) {
  await expect(page.locator(`#saved-project option[value="${id}"]`)).toHaveCount(1);
  await page.getByLabel("保存済み", { exact: true }).selectOption(id);
  await page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeEnabled();
}
const localDatabase = "autonavlog.projects.dev_shared_navmate-6b281";
async function localRows(page: Page, database = localDatabase) {
  return page.evaluate(name => new Promise<any[]>((resolve, reject) => {
    const request = indexedDB.open(name);
    request.onsuccess = () => {
      const db = request.result, tx = db.transaction("projects"), read = tx.objectStore("projects").getAll();
      tx.oncomplete = () => { db.close(); resolve(read.result); };
      tx.onabort = () => reject(tx.error);
    };
  }), database);
}
async function remoteRows(page: Page) {
  return page.evaluate(() => (window as any).devSharedTest.records());
}
async function start(page: Page) {
  await page.route(/https:\/\/.*googleapis\.com\//, route => {
    throw new Error("Unexpected real Firebase request: " + route.request().url());
  });
  await page.goto("/e2e/dev-shared-harness/index.html");
  await enterImportWorkflow(page);
  await expect.poll(() => page.evaluate(() => (window as any).devSharedTest.user().anonymous)).toBe(true);
  await expect(page.getByRole("button", { name: "アカウント", exact: true })).toHaveCount(0);
}
test.beforeEach(async ({ request, page }) => {
  page.on("dialog", dialog => dialog.accept());
  expect((await request.delete("http://127.0.0.1:8089/emulator/v1/projects/navmate-6b281/databases/(default)/documents")).ok()).toBe(true);
});

test("independent desktop and mobile anonymous visitors share Project and NAV LOG", async ({ page, browser, baseURL }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await start(page);
  await create(page, "shared-from-desktop", true);
  const row = (await localRows(page)).find(row => row.checkpoint);
  const navlog = await page.locator(".nav-log-table").textContent();
  await expect.poll(async () => (await remoteRows(page)).find((value: any) => value.id === row.id)?.version)
    .toBe(row.sync.value.version);
  const mobile = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 } });
  const second = await mobile.newPage();
  second.on("dialog", dialog => dialog.accept());
  try {
    await start(second);
    expect(await second.evaluate(() => (window as any).devSharedTest.user().uid))
      .not.toBe(await page.evaluate(() => (window as any).devSharedTest.user().uid));
    await load(second, row.id);
    await expect(second.locator(".nav-log-table")).toHaveText(navlog!);
    await second.getByLabel("プロジェクト", { exact: true }).fill("shared-from-mobile");
    await second.getByRole("button", { name: "保存", exact: true }).click();
    await expect.poll(async () => JSON.parse((await remoteRows(second)).find((value: any) => value.id === row.id)?.payload ?? "null")?.checkpoint?.name)
      .toBe("shared-from-mobile");
    await expect(page.locator(`#saved-project option[value="${row.id}"]`)).toHaveText("shared-from-mobile");
    await load(page, row.id);
    await expect(page.getByLabel("プロジェクト", { exact: true })).toHaveValue("shared-from-mobile");
    for (const width of [1100, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      const input = await page.locator(".input-rail").boundingBox();
      const map = await page.locator(".route-workspace").boundingBox();
      const ready = await page.locator(".status-rail").boundingBox();
      if (width <= 1240) { expect(input!.y + input!.height - 1).toBeLessThanOrEqual(map!.y); expect(map!.y + map!.height - 1).toBeLessThanOrEqual(ready!.y); }
      else { expect(input!.x).toBeLessThan(map!.x); expect(map!.x).toBeLessThan(ready!.x); }
      expect((await page.locator(".nav-log-scroll").boundingBox())!.y).toBeGreaterThan(ready!.y);
    }
  } finally { await mobile.close(); }
});

test("offline edits remain local and synchronize to the development workspace after reconnect", async ({ page, context }) => {
  await start(page);
  await create(page, "online-project");
  const row = (await localRows(page)).find(row => row.checkpoint);
  await expect.poll(async () => (await localRows(page)).find(value => value.id === row.id)?.sync.dirty).toBe(false);
  await context.setOffline(true);
  await page.getByLabel("プロジェクト", { exact: true }).fill("offline-edit");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect.poll(async () => (await localRows(page)).find(value => value.id === row.id)?.checkpoint?.name).toBe("offline-edit");
  expect((await localRows(page)).find(value => value.id === row.id)?.sync.dirty).toBe(true);
  await context.setOffline(false);
  await expect.poll(async () => JSON.parse((await remoteRows(page)).find((value: any) => value.id === row.id)?.payload ?? "null")?.checkpoint?.name)
    .toBe("offline-edit");
  await expect.poll(async () => (await localRows(page)).find(value => value.id === row.id)?.sync.dirty).toBe(false);
});


test("anonymous originals are retained and claimed only into the development namespace", async ({ page }) => {
  await page.goto("/e2e/dev-shared-harness/index.html?ordinary");
  await create(page, "before-dev-sync");
  const original = (await localRows(page, "autonavlog.projects")).find(row => row.checkpoint);
  await start(page);
  await expect.poll(async () => (await localRows(page)).find(row => row.id === original.id)?.sync.dirty).toBe(false);
  const { claimedAccount, ...retained } = (await localRows(page, "autonavlog.projects")).find(row => row.id === original.id);
  expect(claimedAccount).toBe("dev_shared_navmate-6b281");
  expect(retained).toEqual(original);
  await load(page, original.id);
  await page.getByRole("button", { name: "保存済みプロジェクトを削除", exact: true }).click();
  await expect(page.locator(`#saved-project option[value="${original.id}"]`)).toHaveCount(0);
  await expect.poll(async () => (await remoteRows(page)).find((value: any) => value.id === original.id)?.deletion).toBe("PENDING_DELETE");
  await page.reload();
  await enterImportWorkflow(page);
  await expect(page.locator(`#saved-project option[value="${original.id}"]`)).toHaveCount(0);
  expect((await localRows(page, "autonavlog.projects")).find(row => row.id === original.id)?.token).toBe(original.token);
});
