import { test, expect } from "@playwright/test";
import { signInSyncAccount, waitForSyncAccount } from "./helpers/sync-auth";

test("sync sign-in waits for initial UI across a reload", async ({ page }) => {
  const calls: { subject: string; ready: boolean }[] = [];
  await page.exposeFunction("recordSignIn", (subject: string, ready: boolean) => { calls.push({ subject, ready }); });
  let ready = false;
  await page.route("https://readiness.example/", route => route.fulfill({
    contentType: "text/html; charset=utf-8",
    body: `<!doctype html><meta charset="utf-8">${ready ? '<button aria-label="アカウント">Account</button>' : '<p>Loading</p>'}
      <script>window.authTest = { signIn: subject => window.recordSignIn(subject, ${ready}) };</script>`,
  }));
  await page.goto("https://readiness.example/");
  const signingIn = signInSyncAccount(page, "expected");
  // The harness is already callable, but its initial App is not ready yet.
  expect(await page.evaluate(() => Boolean((window as any).authTest))).toBe(true);
  expect(calls).toEqual([]);
  ready = true;
  await page.reload();
  expect(await page.evaluate(() => document.characterSet)).toBe("UTF-8");
  await signingIn;
  expect(calls).toEqual([{ subject: "expected", ready: true }]);
});

test("sync sign-in propagates auth errors without retry", async ({ page }) => {
  await page.setContent(`<button aria-label="アカウント">Account</button><script>
    window.signInCalls = 0;
    window.authTest = { signIn() {
      window.signInCalls++;
      return Promise.reject(new Error("auth/network-request-failed"));
    } };
  </script>`);
  await expect(signInSyncAccount(page, "expected")).rejects.toThrow("auth/network-request-failed");
  expect(await page.evaluate(() => (window as any).signInCalls)).toBe(1);
});

test("sync account readiness survives a reload while the account is pending", async ({ page }) => {
  let restored = false;
  await page.route("https://readiness.example/", route => route.fulfill({
    contentType: "text/html",
    body: `<script>window.authTest = { state() {
      window.readinessPolled = true;
      return { account: { displayName: ${JSON.stringify(restored ? "expected" : "other")} } };
    } };</script>`,
  }));
  await page.goto("https://readiness.example/");
  const ready = waitForSyncAccount(page, "expected");
  await page.waitForFunction(() => (window as any).readinessPolled);
  restored = true;
  await page.reload();
  await ready;
  expect(await page.evaluate(() => (window as any).authTest.state().account.displayName)).toBe("expected");
});

test("sync account readiness rejects a different account", async ({ page }) => {
  await page.setContent("<script>window.authTest = { state: () => ({ account: { displayName: 'other' } }) };</script>");
  await expect(waitForSyncAccount(page, "expected", 250)).rejects.toThrow(/Timeout/);
});
for (const operation of ["resolve", "import"] as const) test("post-" + operation + " refresh failure remains visible without Undo", async ({ page }) => {
  await page.goto(`/e2e/auth-harness/sync-control.html?operation=${operation}`);
  if (operation === "resolve") await page.getByRole("button", { name: "同期先の内容を採用", exact: true }).click();
  else await page.getByRole("button", { name: "破棄", exact: true }).click();
  await expect(page.locator(".account-sync-dialog")).not.toBeVisible();
  await expect(page.getByRole("button", { name: "元に戻す", exact: true })).toHaveCount(0);
  await expect(page.getByRole("alert").filter({ hasText: "Projectの再読み込みに失敗しました" })).toBeVisible();
});


for (const operation of ["resolve", "import"] as const) test("draft guard precedes sync " + operation, async ({ page }) => {
  await page.goto(`/e2e/auth-harness/sync-control.html?operation=${operation}&guard=1`);
  const action = page.getByRole("button", { name: operation === "resolve" ? "同期先の内容を採用" : "破棄", exact: true });
  page.once("dialog", dialog => dialog.dismiss());
  await action.click();
  await expect(page.locator(".account-sync-dialog")).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Projectの再読み込みに失敗しました" })).toHaveCount(0);
  page.once("dialog", dialog => dialog.accept());
  await action.click();
  await expect(page.locator(".account-sync-dialog")).not.toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Projectの再読み込みに失敗しました" })).toBeVisible();
});
