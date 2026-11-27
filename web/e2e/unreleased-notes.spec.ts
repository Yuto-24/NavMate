import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { openInformation } from "./helpers/header";
import { expectPlanningLayout } from "./helpers/planningLayout";
const head = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();

for (const width of [390, 1100, 1440]) {
  test(`Local Docker information at ${width}px`, async ({ page }, testInfo) => {
    const scenario = testInfo.project.name;
    await page.setViewportSize({ width, height: 900 });
    const github: string[] = [], errors: string[] = [];
    page.on("request", request => { if (/github\.com/.test(request.url())) github.push(request.url()); });
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("/");
    await expect(page).toHaveTitle(/NavMate/);
    await expect(page.locator(".app-header")).toBeVisible();
    await openInformation(page);
    const dialog = page.getByRole("dialog", { name: "お知らせ", exact: true });
    await expect(dialog.getByRole("heading", { name: "更新履歴", exact: true })).toBeVisible();
    const tab = dialog.getByRole("tab", { name: "未リリース", exact: true });
    if (scenario === "production") {
      await expect(tab).toHaveCount(0);
      await expect(dialog).not.toContainText("ISSUE543_UNRELEASED_SENTINEL");
    } else {
      await tab.click();
      const panel = dialog.getByRole("tabpanel", { name: "未リリース", exact: true });
      await expect(panel).toBeVisible();
      await expect(panel.getByRole("link", { name: head })).toHaveAttribute("href", `https://github.com/Yuto-24/NavMate/commit/${head}`);
      if (scenario === "ready") {
        const pr = panel.getByRole("link", { name: "#543 ISSUE543_UNRELEASED_SENTINEL" });
        await expect(pr).toHaveAttribute("href", "https://github.com/Yuto-24/NavMate/pull/543");
        await expect(pr).toHaveAttribute("rel", "noopener noreferrer");
        await expect(panel).toContainText("このビルドに含まれる変更を確認できます。");
        await expect(panel).toContainText("基準リリース");
      } else if (scenario === "empty") {
        await expect(panel).toContainText("未リリースの変更はありません。");
        await expect(panel.getByRole("link", { name: /#543/ })).toHaveCount(0);
      } else {
        await expect(panel.getByRole("status")).toHaveText("未リリースの変更を取得できませんでした。次回ビルド時に再取得します。");
        await expect(panel).not.toContainText("未リリースの変更はありません。");
      }
      await expect(dialog.getByRole("heading", { name: "更新履歴", exact: true })).toHaveCount(0);
      await page.screenshot({ path: testInfo.outputPath("information.png") });
      await tab.press("ArrowLeft");
      await expect(dialog.getByRole("tab", { name: "お知らせ", exact: true })).toBeFocused();
      await expect(dialog.getByRole("heading", { name: "更新履歴", exact: true })).toBeVisible();
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    // Information must not change the underlying workflow geometry.
    await expectPlanningLayout(page, width);
    expect(github).toEqual([]);
    expect(errors).toEqual([]);
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  });
}
