import { expect, type Page } from "@playwright/test";

/** Click a geographic point through the rendered map, without mutating app state. */
export async function clickMapCoordinate(page: Page, latitude: number, longitude: number) {
  const map = page.locator(".route-map");
  await map.scrollIntoViewIfNeeded();
  for (let attempt = 0; attempt < 8; attempt++) {
    const view = await page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!));
    const box = (await map.boundingBox())!;
    const project = (lat: number, lon: number) => {
      const scale = 256 * 2 ** view.zoom, sine = Math.sin(lat * Math.PI / 180);
      return [scale * (lon + 180) / 360, scale * (0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI))];
    };
    const target = project(latitude, longitude), center = project(view.latitude, view.longitude);
    const x = box.width / 2 + target[0]! - center[0]!, y = box.height / 2 + target[1]! - center[1]!;
    if (x > 45 && x < box.width - 45 && y > 65 && y < box.height - 65) {
      await map.click({ position: { x, y } });
      return;
    }
    await page.getByRole("button", { name: "Zoom out", exact: true }).click();
    await expect.poll(async () => page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!).zoom)).toBe(view.zoom - 1);
  }
  throw new Error("Test coordinate did not enter the visible map");
}
