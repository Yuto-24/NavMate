import { openProjectMenu } from "./helpers/header";
import { test, expect, type Page } from "@playwright/test";
import { resolve } from "node:path";
import { initializeApp, deleteApp } from "firebase/app";
import { connectFirestoreEmulator, doc, getFirestore, setDoc, terminate } from "firebase/firestore";
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
  await openProjectMenu(page);
  await page.getByLabel("プロジェクト", { exact: true }).fill(name);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
}
async function load(page: Page, id: string) {
  await expect(page.locator(`#saved-project option[value="${id}"]`)).toHaveCount(1);
  await openProjectMenu(page);
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
  await expect(page.getByRole("button", { name: /^アカウント(?:（|$)/ })).toBeVisible();
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
    await openProjectMenu(second);
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
  await openProjectMenu(page);
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
  await openProjectMenu(page);
  await page.getByRole("button", { name: "保存済みプロジェクトを削除", exact: true }).click();
  await expect(page.locator(`#saved-project option[value="${original.id}"]`)).toHaveCount(0);
  await expect.poll(async () => (await remoteRows(page)).find((value: any) => value.id === original.id)?.deletion).toBe("PENDING_DELETE");
  await page.reload();
  await enterImportWorkflow(page);
  await expect(page.locator(`#saved-project option[value="${original.id}"]`)).toHaveCount(0);
  expect((await localRows(page, "autonavlog.projects")).find(row => row.id === original.id)?.token).toBe(original.token);
});

async function googleLogin(page: Page, subject: string) {
  await page.evaluate(subject => (window as any).devSharedTest.selectGoogle(subject), subject);
  await page.getByRole("button", { name: /^アカウント(?:（|$)/ }).click();
  await page.getByRole("button", { name: "Googleでログイン", exact: true }).click();
  await enterImportWorkflow(page);
  await expect(page.locator(".storage-state")).toHaveText("端末・個人保存");
}
async function logout(page: Page) {
  await page.getByRole("button", { name: /^アカウント(?:（|$)/ }).click();
  await page.getByRole("button", { name: "ログアウト", exact: true }).click();
  await enterImportWorkflow(page);
  await expect(page.locator(".storage-state")).toHaveText("端末・共有保存");
}

test("Google accounts switch away from shared Projects, sync privately, and delete only dev personal data", async ({ page, browser, baseURL }) => {
  await start(page);
  await create(page, "shared-stays");
  const shared = (await localRows(page)).find(row => row.checkpoint);
  await expect.poll(async () => (await remoteRows(page)).some((row: any) => row.id === shared.id)).toBe(true);
  await googleLogin(page, "dev-google-one");
  await expect(page.locator(`#saved-project option[value="${shared.id}"]`)).toHaveCount(0);
  await create(page, "personal-one", true);
  const personalDatabase = await page.evaluate(async () => (await indexedDB.databases())
    .find(db => db.name?.startsWith("autonavlog.projects.dev_navmate-6b281.account_"))!.name!);
  const personal = (await localRows(page, personalDatabase)).find(row => row.checkpoint);
  await expect.poll(async () => (await localRows(page, personalDatabase)).find(row => row.id === personal.id)?.sync.dirty).toBe(false);
  const navlog = await page.locator(".nav-log-table").textContent();
  expect((await remoteRows(page)).some((row: any) => row.id === personal.id)).toBe(false);

  // Simulate older production-backed local data at this same origin. Dev account
  // deletion must preserve this exact namespace and identity cache.
  const accountId = personalDatabase.split("dev_navmate-6b281.")[1]!;
  await page.evaluate(async ({ accountId }) => {
    localStorage.setItem("autonavlog.account.current.dev-google-one", accountId);
    localStorage.setItem(`autonavlog.map-viewport.v1.${accountId}.last`, "production-marker");
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open(`autonavlog.projects.${accountId}`, 2);
      request.onupgradeneeded = () => request.result.createObjectStore("projects", { keyPath: "id" });
      request.onsuccess = () => {
        const db = request.result, tx = db.transaction("projects", "readwrite");
        tx.objectStore("projects").put({ id: "production-marker" });
        tx.oncomplete = () => { db.close(); resolve(); }; tx.onerror = () => reject(tx.error);
      };
    });
  }, { accountId });

  const mobile = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 } });
  const second = await mobile.newPage();
  second.on("dialog", dialog => dialog.accept());
  try {
    await start(second);
    await googleLogin(second, "dev-google-two");
    await expect(second.locator(`#saved-project option[value="${personal.id}"]`)).toHaveCount(0);
    await logout(second);
    await googleLogin(second, "dev-google-one");
    await load(second, personal.id);
    await expect(second.locator(".nav-log-table")).toHaveText(navlog!);
    await logout(second);
    await load(second, shared.id);
    await expect(second.locator(`#saved-project option[value="${personal.id}"]`)).toHaveCount(0);
  } finally { await mobile.close(); }
  await logout(page);
  await load(page, shared.id);
  await googleLogin(page, "dev-google-one");
  await load(page, personal.id);
  await expect(page.locator(".nav-log-table")).toHaveText(navlog!);
  await page.getByRole("button", { name: /^アカウント(?:（|$)/ }).click();
  await page.getByRole("button", { name: "アカウントを削除", exact: true }).click();
  await page.getByRole("button", { name: "NavMateアカウントを削除する", exact: true }).click();
  await enterImportWorkflow(page);
  await expect(page.getByRole("alert")).toContainText("NavMateアカウントを削除しました");
  await load(page, shared.id);
  expect(await localRows(page, `autonavlog.projects.${accountId}`)).toEqual([{ id: "production-marker" }]);
  expect(await page.evaluate(() => localStorage.getItem("autonavlog.account.current.dev-google-one"))).toBe(accountId);
  expect(await page.evaluate(id => localStorage.getItem(`autonavlog.map-viewport.v1.${id}.last`), accountId)).toBe("production-marker");
  await googleLogin(page, "dev-google-one");
  await expect(page.locator(`#saved-project option[value="${personal.id}"]`)).toHaveCount(0);
  await expect(page.locator(`#saved-project option[value="${shared.id}"]`)).toHaveCount(0);
  await create(page, "personal-new-generation");
  const nextDatabase = await page.evaluate(async () => (await indexedDB.databases())
    .find(db => db.name?.startsWith("autonavlog.projects.dev_navmate-6b281.account_v2_"))!.name!);
  await expect.poll(async () => (await localRows(page, nextDatabase)).find(row => row.checkpoint)?.sync.dirty).toBe(false);
  await logout(page);
  await load(page, shared.id);
});

test("a personal account ID matching the shared namespace cannot open or purge shared browser data", async ({ page }) => {
  await start(page);
  await create(page, "shared-private-boundary");
  const shared = (await localRows(page)).find(row => row.checkpoint);
  const alias = "dev_shared_navmate-6b281";
  const app = initializeApp({ projectId: "navmate-6b281" }, crypto.randomUUID());
  const db = getFirestore(app);
  connectFirestoreEmulator(db, "127.0.0.1", 8089, { mockUserToken: {
    sub: "alias-owner", firebase: { sign_in_provider: "google.com", identities: { "google.com": ["dev-google-alias"] } },
  } });
  try {
    // Existing account records permit arbitrary strings; they are not trusted
    // to select a shared or old production browser namespace.
    await setDoc(doc(db, "googleAccounts", "dev-google-alias"), { schema: 1, state: "ACTIVE", accountId: alias });
  } finally { await terminate(db); await deleteApp(app); }
  await googleLogin(page, "dev-google-alias");
  await expect(page.locator(`#saved-project option[value="${shared.id}"]`)).toHaveCount(0);
  const personalDatabase = `autonavlog.projects.dev_navmate-6b281.${alias}`;
  await expect.poll(() => page.evaluate(async name => (await indexedDB.databases()).some(db => db.name === name), personalDatabase)).toBe(true);
  expect((await localRows(page, personalDatabase)).some(row => row.id === shared.id)).toBe(false);
  await logout(page);
  await page.evaluate(async id => {
    const { removeLocalAccount } = await import("/src/accountLifecycle.ts");
    await removeLocalAccount(id);
  }, alias);
  await load(page, shared.id);
  expect((await localRows(page)).some(row => row.id === shared.id)).toBe(true);
});
