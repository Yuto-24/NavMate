import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { buildHead } from "../scripts/unreleased-notes.mjs";
import { openInformation } from "./helpers/header";
import { expectPlanningLayout } from "./helpers/planningLayout";
const head = buildHead(fileURLToPath(new URL("../..", import.meta.url)));

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
    if (scenario !== "production") {
      const close = dialog.getByRole("button", { name: "お知らせを閉じる", exact: true });
      const history = dialog.getByRole("tab", { name: "お知らせ", exact: true });
      await expect(close).toBeFocused();
      await close.press("Shift+Tab");
      await expect(history).toBeFocused();
      await history.press("Tab");
      await expect(close).toBeFocused();
    }
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
      await tab.press("Tab");
      await expect(panel.getByRole("link").first()).toBeFocused();
      const last = panel.getByRole("link").last();
      await last.press("Tab");
      const close = dialog.getByRole("button", { name: "お知らせを閉じる", exact: true });
      await expect(close).toBeFocused();
      await close.press("Shift+Tab");
      await expect(last).toBeFocused();
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
