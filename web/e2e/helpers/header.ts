import { expect, type Page } from "@playwright/test";

export async function openProjectMenu(page: Page) {
  const button = page.getByRole("button", { name: "プロジェクトメニュー", exact: true });
  await expect(button).toBeVisible();
  if (await button.getAttribute("aria-expanded") !== "true") await button.click();
}

export async function openInformation(page: Page) {
  await page.getByRole("button", { name: /^その他/ }).click();
  await page.getByRole("button", { name: /^お知らせ/ }).click();
}
