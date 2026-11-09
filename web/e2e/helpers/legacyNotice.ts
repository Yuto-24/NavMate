import { expect, test, type Page } from "@playwright/test";

// Explicitly enter the existing workflow after each Legacy navigation/reload.
// Local-mode suites share some scenarios but never render this Legacy-only notice.
export async function dismissLegacyNotice(page: Page) {
  if (test.info().config.metadata.applicationMode === "local") return;
  const dismiss = page.getByRole("button", { name: "今回はスキップ", exact: true });
  await expect(dismiss).toBeVisible({ timeout: 120_000 });
  await dismiss.click();
  await expect(dismiss).toHaveCount(0);
}
