import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { enterImportWorkflow, confirmImportedDraft } from "./helpers/importWorkflow";
import { openProjectMenu, openInformation } from "./helpers/header";

async function assertHeader(page: Page, width: number) {
  const geometry = await page.evaluate(() => {
    const rect = (element: Element) => {
      const { x, y, width, height } = element.getBoundingClientRect();
      return { x, y, width, height };
    };
    const header = document.querySelector(".app-header")!;
    return { header: rect(header), controls: Array.from(header.querySelectorAll(".brand-block, .project-menu-button, .header-actions > button, .header-more-button"), rect),
      overflow: document.documentElement.scrollWidth - innerWidth };
  });
  expect(geometry.header.y).toBe(0);
  expect(geometry.header.height).toBe(56);
  expect(geometry.overflow).toBeLessThanOrEqual(1);
  expect(geometry.controls).toHaveLength(6);
  for (const [index, box] of geometry.controls.entries()) {
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(56);
    expect(box.width).toBeGreaterThan(0);
    if (index) expect(box.x).toBeGreaterThanOrEqual(geometry.controls[index - 1]!.x + geometry.controls[index - 1]!.width);
  }
  await expect(page.locator(".app-header")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(page.locator(".brand-block img")).toHaveJSProperty("naturalWidth", 192);
}

async function assertWorkflow(page: Page, width: number) {
  const boxes = await page.evaluate(() => [".input-rail", ".route-workspace", ".status-rail", ".nav-log-focus-target"].map(selector => {
    const { x, y, width, height } = document.querySelector(selector)!.getBoundingClientRect();
    return { x, y, width, height };
  }));
  if (width <= 1240) {
    for (let i = 1; i < boxes.length; i++) expect(boxes[i]!.y).toBeGreaterThanOrEqual(boxes[i - 1]!.y + boxes[i - 1]!.height - 1);
  } else {
    for (let i = 1; i < 3; i++) {
      expect(boxes[i]!.x).toBeGreaterThanOrEqual(boxes[i - 1]!.x + boxes[i - 1]!.width - 1);
      expect(boxes[i]!.y).toBe(boxes[0]!.y);
    }
    expect(boxes[3]!.y).toBeGreaterThanOrEqual(Math.max(...boxes.slice(0, 3).map(b => b.y + b.height)) - 1);
  }
}

test("#218 single-row sticky header preserves workflow, long names and keyboard/menu access", async ({ page }, info) => {
  await page.goto("/");
  await enterImportWorkflow(page);
  await page.setViewportSize({ width: 320, height: 900 });
  await assertHeader(page, 320);
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  await openProjectMenu(page);
  await expect(page.getByLabel("プロジェクト", { exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "プロジェクトメニュー", exact: true })).toBeFocused();

  await page.locator('input[type="file"]').setInputFiles(fileURLToPath(new URL("../../tests/fixtures/issue_43_golden.kml", import.meta.url)));
  await confirmImportedDraft(page);
  await page.getByLabel("DATE", { exact: true }).fill("2026-09-11");
  await page.getByLabel("ETD JST", { exact: true }).fill("09:00");
  await page.getByLabel("気象モード").selectOption("FTD");
  for (const [name, altitude] of [["RJFM", "6500"], ["米ノ津", "7500"], ["玉名", "6500"]]) {
    await page.getByLabel(`${name}出発Legの計画高度`, { exact: true }).fill(altitude);
  }
  await page.getByRole("button", { name: "NAV LOGを作る", exact: true }).click();
  await expect(page.locator(".nav-log-table")).toBeVisible();
  const result = await page.locator(".nav-log-table").innerText();
  const longName = "長いプロジェクト名を狭い画面でも全文確認する".repeat(2);
  await openProjectMenu(page);
  await page.getByLabel("プロジェクト", { exact: true }).fill(longName);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();

  await openProjectMenu(page);
  const selectedId = await page.getByLabel("保存済み", { exact: true }).inputValue();
  const revision = await page.locator(".header-revision").textContent();
  await page.getByLabel("保存済み", { exact: true }).selectOption("");
  await expect(page.locator(".nav-log-table")).toHaveText(result, { useInnerText: true });
  await expect(page.locator(".header-revision")).toHaveText(revision!);
  await expect(page.getByRole("button", { name: "保存済みプロジェクトを削除", exact: true })).toBeDisabled();
  await page.getByLabel("保存済み", { exact: true }).selectOption(selectedId);
  await expect(page.locator(".header-revision")).toHaveText(revision!);
  await page.keyboard.press("Escape");

  for (const width of [320, 390, 1100, 1239, 1240, 1241, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => scrollTo({ top: 0, behavior: "instant" }));
    await assertHeader(page, width);
    const rail = await page.locator(".progress-rail").boundingBox();
    expect(rail!.y).toBeGreaterThanOrEqual(56);
    await assertWorkflow(page, width);
    await page.screenshot({ path: info.outputPath(`header-${width}.png`) });
    await page.evaluate(() => scrollTo({ top: 600, behavior: "instant" }));
    await assertHeader(page, width);
    await assertWorkflow(page, width);
    const notice = page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" });
    const noticeBounds = await notice.boundingBox();
    expect(noticeBounds!.y).toBe(56);
    await expect(notice.getByRole("button", { name: "メッセージを閉じる" })).toBeInViewport();
    expect(await notice.evaluate(el => {
      const box = el.getBoundingClientRect();
      return el.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
    })).toBe(true);
    await page.screenshot({ path: info.outputPath(`header-scrolled-${width}.png`) });

    const project = page.getByRole("button", { name: "プロジェクトメニュー", exact: true });
    await project.focus();
    await page.keyboard.press("Enter");
    await expect(project).toHaveAttribute("aria-expanded", "true");
    await expect(project).toHaveAccessibleDescription(longName);
    await expect(page.locator(".header-project-full-name")).toHaveText(longName);
    if (width === 320 || width === 1440) await page.screenshot({ path: info.outputPath(`project-menu-${width}.png`) });
    const panel = await page.locator(".project-panel").boundingBox();
    expect(panel!.y).toBeGreaterThanOrEqual(56);
    expect(panel!.x).toBeGreaterThanOrEqual(0);
    expect(panel!.x + panel!.width).toBeLessThanOrEqual(width);
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("プロジェクト", { exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(project).toBeFocused();
    await expect(project).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("Space");
    await page.keyboard.press("Shift+Tab");
    await expect(project).toHaveAttribute("aria-expanded", "false");

    await page.getByRole("button", { name: /^その他/ }).click();
    await expect(page.locator(".brand-subtitle")).toContainText(/NAV2 地上準備 \/ v\d/);
    await expect(page.locator(".storage-state")).toContainText("端末内に保存");
    const informationButton = page.getByRole("button", { name: /^お知らせ/ });
    const informationBox = await informationButton.boundingBox();
    const moreBox = await page.locator(".more-panel").boundingBox();
    expect(informationBox!.width).toBeGreaterThan(moreBox!.width - 40);
    expect(await informationButton.locator("span").evaluate(el => el.getBoundingClientRect().height)).toBeLessThan(25);
    if (width === 320 || width === 1440) await page.screenshot({ path: info.outputPath(`more-menu-${width}.png`) });
    await project.click();
    await expect(page.locator(".more-panel")).toBeHidden();
    await page.mouse.click(width / 2, 500);
    await expect(page.locator(".project-panel")).toBeHidden();
    await openInformation(page);
    const dialog = page.getByRole("dialog", { name: "お知らせ", exact: true });
    await expect(dialog).toBeVisible();
    expect(await page.evaluate(() => document.elementFromPoint(10, 10)?.classList.contains("modal-backdrop"))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "その他", exact: true })).toBeFocused();
  }
  await expect(page.locator(".nav-log-table")).toHaveText(result, { useInnerText: true });
  // Native focus scrolling must reserve the fixed header's height.
  await page.getByLabel("DATE", { exact: true }).focus();
  const date = await page.getByLabel("DATE", { exact: true }).boundingBox();
  expect(date!.y).toBeGreaterThanOrEqual(56);
});

test("#218 panel pointer actions survive input blur and keyboard departure still closes panels", async ({ page }) => {
  await page.goto("/");
  await enterImportWorkflow(page);
  await page.locator('input[type="file"]').setInputFiles(fileURLToPath(new URL("../../tests/fixtures/issue_43_golden.kml", import.meta.url)));
  await confirmImportedDraft(page);
  await openProjectMenu(page);
  const name = page.getByLabel("プロジェクト", { exact: true });
  await name.fill("Panel pointer route");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "プロジェクトを保存しました" })).toBeVisible();
  await openProjectMenu(page);
  const selector = page.getByLabel("保存済み", { exact: true });
  const id = await selector.inputValue();
  await selector.selectOption(id);
  await name.fill("Unsaved name");
  const confirmations: string[] = [];
  page.on("dialog", async dialog => {
    confirmations.push(dialog.message());
    await dialog.accept();
  });
  // Linux WebKit can focus clicked buttons. Reproduce Safari's null-relatedTarget
  // transition using a real DOM blur between mousedown and click.
  for (const label of ["保存済みプロジェクトを開く", "保存済みプロジェクトを削除"]) {
    await page.getByRole("button", { name: label, exact: true }).evaluate(button => {
      button.addEventListener("mousedown", () => document.getElementById("project-name")!.blur(), { once: true });
    });
  }
  await page.getByRole("button", { name: "保存済みプロジェクトを開く", exact: true }).click({ timeout: 5000 });
  await expect(name).toHaveValue("Panel pointer route");
  expect(confirmations).toHaveLength(1);
  await openProjectMenu(page);
  await name.focus();
  await page.getByRole("button", { name: "保存済みプロジェクトを削除", exact: true }).click({ timeout: 5000 });
  await expect(selector.locator(`option[value="${id}"]`)).toHaveCount(0);
  expect(confirmations).toHaveLength(2);

  const project = page.getByRole("button", { name: "プロジェクトメニュー", exact: true });
  await openProjectMenu(page);
  await selector.focus();
  await page.keyboard.press("Tab");
  await expect(project).toHaveAttribute("aria-expanded", "false");
  const more = page.getByRole("button", { name: /^その他/ });
  await more.focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: /^お知らせ/ }).click({ timeout: 5000 });
  await expect(page.getByRole("dialog", { name: "お知らせ", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await more.press("Enter");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(more).toHaveAttribute("aria-expanded", "false");
});
