import type { Page } from "@playwright/test";

export async function observeCalculationProgress(page: Page) {
  await page.evaluate(() => {
    const values: number[] = [];
    const observer = new MutationObserver(() => {
      const bar = document.querySelector<HTMLProgressElement>(".calculation-progress-dialog progress");
      if (bar && values.at(-1) !== bar.value) values.push(bar.value);
    });
    observer.observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ["value"] });
    Object.assign(window, { finishProgressObservation: () => {
      observer.disconnect();
      return values;
    } });
  });
  return () => page.evaluate(() => (window as any).finishProgressObservation() as number[]);
}
