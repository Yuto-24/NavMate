import { test, expect, type Page } from "@playwright/test";
import { resolve } from "node:path";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";

const headers = { "X-NavMate-Dev-Storage": "1" };
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
  await page.getByLabel("保存済み", { exact: true }).selectOption(id);
  const opened = page.waitForResponse(response => response.url().endsWith("/api/dev-projects/open")
    && response.request().method() === "POST");
  await page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true }).click();
  expect((await opened).status()).toBe(200);
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeEnabled();
}
async function originals(page: Page) {
  return page.evaluate(() => new Promise<any[]>((resolve, reject) => {
    const request = indexedDB.open("autonavlog.projects");
    request.onsuccess = () => {
      const db = request.result;
      const tx = db.transaction("projects");
      const read = tx.objectStore("projects").getAll();
      tx.oncomplete = () => { db.close(); resolve(read.result); };
      tx.onabort = () => reject(tx.error);
    };
  }));
}

test.beforeEach(async ({ request, page }) => {
  page.on("dialog", dialog => dialog.accept());
  const { records } = await (await request.get("/api/dev-projects", { headers })).json();
  for (const record of records) await request.post("/api/dev-projects/delete", {
    headers, data: { id: record.id, expectedToken: record.token },
  });
});

test("independent desktop and mobile browsers resume the same Project and NAV LOG without Google", async ({ page, browser, baseURL }) => {
  const forbidden: string[] = [];
  page.on("request", request => { if (/googleapis|firebase|identitytoolkit/.test(request.url())) forbidden.push(request.url()); });
  await page.setViewportSize({ width: 1100, height: 1000 });
  await page.goto("/");
  await expect(page.getByLabel("アカウント", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("サーバー保存（dev環境共有）", { exact: true })).toBeVisible();
  await create(page, "Shared desktop", true);
  const shared = await (await page.request.get("/api/dev-projects", { headers })).json();
  expect(shared.records).toHaveLength(1);
  const record = shared.records[0];
  expect(record.lastCalculation).not.toBeNull();
  const navlog = await page.locator(".nav-log-table").textContent();
  for (const width of [1100, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    const boxes = await Promise.all([".input-rail", ".route-workspace", ".status-rail", ".nav-log-scroll"]
      .map(selector => page.locator(selector).boundingBox()));
    const [input, route, readiness, log] = boxes.map(box => { expect(box).not.toBeNull(); return box!; });
    if (width <= 1240) {
      expect(route!.y).toBeGreaterThanOrEqual(input!.y + input!.height - 1);
      expect(readiness!.y).toBeGreaterThanOrEqual(route!.y + route!.height - 1);
    } else {
      expect(input!.x).toBeLessThan(route!.x);
      expect(route!.x).toBeLessThan(readiness!.x);
      expect(Math.abs(input!.y - readiness!.y)).toBeLessThan(10);
    }
    expect(log!.y).toBeGreaterThan(readiness!.y);
  }
  const mobile = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  try {
    const phone = await mobile.newPage();
    phone.on("dialog", dialog => dialog.accept());
    phone.on("request", request => { if (/googleapis|firebase|identitytoolkit/.test(request.url())) forbidden.push(request.url()); });
    await phone.goto("/");
    await load(phone, record.id);
    await expect(phone.getByLabel("プロジェクト", { exact: true })).toHaveValue("Shared desktop");
    await expect(phone.locator(".nav-log-table")).toHaveText(navlog!);
    await phone.getByLabel("プロジェクト", { exact: true }).fill("Continued on phone");
    await phone.getByRole("button", { name: "保存", exact: true }).click();
    await expect(phone.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
    await page.reload();
    await load(page, record.id);
    await expect(page.getByLabel("プロジェクト", { exact: true })).toHaveValue("Continued on phone");
    await expect(page.locator(".nav-log-table")).toBeVisible();
    expect(forbidden).toEqual([]);
    // Losing the shared server must not report a successful save or mutate its last good copy.
    await phone.reload();
    await load(phone, record.id);
    let rejectedRequests = 0;
    await phone.route(/\/api\/dev-projects(?:\/.*)?$/, route => {
      rejectedRequests++;
      return route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"UNAVAILABLE"}' });
    });
    await phone.getByLabel("プロジェクト", { exact: true }).fill("Cannot save");
    await phone.getByRole("button", { name: "保存", exact: true }).click();
    await expect(phone.getByRole("alert").filter({ hasText: /サーバーに接続できません|プロジェクトを自動保存できませんでした/ }).first()).toBeVisible();
    expect(rejectedRequests).toBeGreaterThan(0);
    await expect(phone.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toHaveCount(0);
    const retained = await (await page.request.get("/api/dev-projects", { headers })).json();
    expect(retained.records[0].checkpoint.name).toBe("Continued on phone");
    expect(retained.records[0].lastCalculation).not.toBeNull();
  } finally { await mobile.close(); }
});

test("ordinary browser storage is preserved and copied once; deletion does not reimport originals", async ({ page }) => {
  // The same bundle without the local runtime marker follows the unchanged browser-only path.
  await page.route("**/", async route => {
    const response = await route.fetch();
    const body = (await response.text()).replace('<meta name="navmate-dev-shared-projects" content="1">', "");
    await route.fulfill({ response, body });
  });
  await page.goto("/");
  await expect(page.getByText("端末内に保存", { exact: true })).toBeVisible();
  await create(page, "Existing local project");
  const saved = (await originals(page))[0];
  await page.getByLabel("ETD JST", { exact: true }).fill("10:00");
  await page.getByLabel("ETD JST", { exact: true }).blur();
  await expect.poll(async () => (await originals(page))[0].token).not.toBe(saved.token);
  const before = await originals(page);
  expect(before).toHaveLength(1);
  expect((await (await page.request.get("/api/dev-projects", { headers })).json()).records).toEqual([]);
  await page.unroute("**/");
  await page.reload();
  await expect(page.getByLabel("サーバー保存（dev環境共有）", { exact: true })).toBeVisible();
  await expect.poll(async () => (await (await page.request.get("/api/dev-projects", { headers })).json()).records.length).toBe(1);
  await load(page, before[0].id);
  await expect(page.getByLabel("プロジェクト", { exact: true })).toHaveValue("Existing local project");
  await expect(page.getByLabel("ETD JST", { exact: true })).toHaveValue("09:00");
  expect(await originals(page)).toEqual(before);
  const reopened = (await (await page.request.get("/api/dev-projects", { headers })).json()).records[0];
  expect(reopened.token).not.toBe(before[0].token);
  await page.request.post("/api/dev-projects/delete", { headers, data: { id: before[0].id, expectedToken: reopened.token } });
  await page.reload();
  await expect(page.getByLabel("保存済み", { exact: true }).locator("option")).toHaveCount(1);
  expect(await originals(page)).toEqual(before);
  expect((await (await page.request.get("/api/dev-projects", { headers })).json()).records).toEqual([]);
});
