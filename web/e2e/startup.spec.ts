import { expect, test } from "@playwright/test";

test("#355 Legacy startup retry keeps the document and displays safe error codes", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/application-session", route => {
    attempts++;
    return route.fulfill({ status: 503, json: { error: {
      message: "処理に失敗しました。",
      code: attempts === 1 ? "REQUEST_FAILED" : "internal/path?token=private",
    } } });
  });
  await page.goto("/");
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("処理に失敗しました。");
  await expect(alert.locator("code")).toHaveText("REQUEST_FAILED");
  const firstDocument = await page.evaluate(() => performance.timeOrigin);
  await page.getByRole("button", { name: "起動を再試行", exact: true }).click();
  await expect(alert.locator("code")).toHaveText("APPLICATION_UNAVAILABLE");
  await expect(page.locator("body")).not.toContainText("token=private");
  expect(attempts).toBe(2);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(firstDocument);
});
