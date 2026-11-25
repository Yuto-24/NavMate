// Manual, deterministic DEM benchmark. Prepare its directory with benchmark_sea.py.
import { readFile, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { createServer } from "node:http";
import { transformWithOxc } from "vite";
import { chromium, webkit, devices } from "@playwright/test";

const directory = resolve(process.argv[2]);
const plans = JSON.parse(await readFile(join(directory, "plans.json"), "utf8"));
for (const version of ["before", "after"]) {
  for (const name of ["sea", "terrain", "terrainTransport", ...(version === "after" ? ["seaCache"] : [])]) {
    const source = await readFile(join(directory, `${version}-${name}.ts`), "utf8");
    const compiled = (await transformWithOxc(source, `${name}.ts`, { target: "es2022" }))
      .code.replace(/from "\.\/(\w+)"/g, `from "./${version}-$1.js"`);
    await writeFile(join(directory, `${version}-${name}.js`), compiled);
  }
}
const server = createServer(async (req, res) => {
  const file = req.url.slice(1);
  if (!/^(before|after)-\w+\.js$/.test(file)) { res.end("<!doctype html><title>SEA benchmark</title>"); return; }
  res.setHeader("Content-Type", "text/javascript");
  res.end(await readFile(join(directory, file)));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const url = `http://127.0.0.1:${server.address().port}`;
const results = [];
try {
  for (const [profile, type, device] of [
    ["chromium", chromium, "Desktop Chrome"],
    ["ipad-webkit", webkit, "iPad (gen 7)"],
    ["iphone-webkit", webkit, "iPhone 13"],
  ]) {
    const browser = await type.launch(profile === "chromium" ? { args: ["--enable-precise-memory-info"] } : {});
    try {
      // This is a bounded observation per profile, not a statistical timing study.
      for (const version of ["before", "after"]) {
        const context = await browser.newContext(devices[device]);
        const page = await context.newPage();
        await page.goto(url);
        const measured = await page.evaluate(async ({ version, plans }) => {
          const { acquireSea } = await import(`/${version}-sea.js`);
          const cache = version === "after" ? new (await import("/after-seaCache.js")).SeaEvaluationCache() : undefined;
          const rows = [];
          for (const [index, plan] of plans.entries()) {
            let tileRequests = 0, observedHeapBytes = null;
            const sample = () => {
              if (performance.memory) observedHeapBytes = Math.max(observedHeapBytes ?? 0, performance.memory.usedJSHeapSize);
            };
            const metrics = { tileRequests: 0, regionEvaluations: 0, regionHits: 0, evaluatedPixels: 0 };
            const started = performance.now();
            const values = await acquireSea(plan, new AbortController().signal, {
              tile: async (x, y) => {
                tileRequests++; sample();
                return { status: "available", elevations: Array(65536).fill(100 + (x + y) % 100),
                  provenance: { source: "synthetic", unit: "m", horizontalReference: "XYZ", verticalReference: "fixture",
                    url: `https://example.test/${x}/${y}`, acquiredAt: "2026-11-26T00:00:00Z", sha256: "a".repeat(64) } };
              },
            }, { cache, metrics });
            const elapsedMs = performance.now() - started;
            sample();
            rows.push({ scenario: ["cold", "move-cp", "delete-cp"][index], elapsedMs, tileRequests,
              evaluatedPixels: version === "after" ? metrics.evaluatedPixels : Object.values(values).reduce((n, v) => n + v.required, 0),
              regionHits: metrics.regionHits, retainedBytes: cache?.retainedBytes ?? 0, observedHeapBytes,
              complete: Object.values(values).every(v => v.complete) });
          }
          return rows;
        }, { version, plans: plans[version] });
        results.push({ profile, version, measurements: measured });
        console.log(JSON.stringify(results.at(-1)));
        await context.close();
      }
    } finally { await browser.close(); }
  }
  await writeFile(join(directory, "results.json"), JSON.stringify({
    baseline: plans.baseline_ref, distanceNm: plans.distance_nm,
    node: process.version, platform: process.platform, results,
  }, null, 2) + "\n");
} finally { server.close(); }
