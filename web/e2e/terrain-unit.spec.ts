import { expect, test } from "@playwright/test";
import { acquireTerrainCoverage, decodeDemRgba, planTerrainCoverage, type LonLat, type TileInput } from "../src/terrain";
import { GsiDemSource } from "../src/terrainTransport";

// Independent inverse XYZ fixture: a polygon crossing x/y tile boundaries in Miyazaki.
function coordinate(x: number, y: number): LonLat {
  return [x / 4194304 * 360 - 180, Math.atan(Math.sinh(Math.PI * (1 - 2 * y / 4194304))) * 180 / Math.PI];
}
const x = 14174 * 256, y = 6668 * 256;
const region = [[x - .2, y - .2], [x + .2, y - .2], [x + .2, y + .2], [x - .2, y + .2]].map(p => coordinate(p[0]!, p[1]!));
const provenance = { source: "fixture", horizontalReference: "XYZ", verticalReference: "TP", unit: "m" as const,
  url: "https://example.test/dem", acquiredAt: "2026-11-09T00:00:00Z", sha256: "a".repeat(64) };
const available = (): TileInput => ({ status: "available", elevations: Array(65536).fill(100), provenance });

test("signed RGB, zero and missing are distinct; alpha and dimensions are rejected", () => {
  const rgba = new Uint8ClampedArray(65536 * 4);
  for (let i = 3; i < rgba.length; i += 4) rgba[i] = 255;
  rgba.set([0, 0, 1, 255, 255, 255, 255, 255, 128, 0, 0, 255]);
  expect(decodeDemRgba(rgba).slice(0, 4)).toEqual([.01, -.01, null, 0]);
  rgba[3] = 0;
  expect(() => decodeDemRgba(rgba)).toThrow("dem-alpha");
  expect(() => decodeDemRgba(rgba.slice(4))).toThrow("dem-dimensions");
});

test("closed footprints include tiny polygons and exact tile/pixel edges", () => {
  const plan = planTerrainCoverage(region);
  expect(plan.counts).toEqual({ required: 4, valid: 0, missing: 0, notAcquired: 4, invalid: 0 });
  expect(plan.tiles.map(t => [t.x, t.y, t.pixels])).toEqual([
    [14173, 6667, [65535]], [14174, 6667, [65280]], [14173, 6668, [255]], [14174, 6668, [0]],
  ]);
  const exact = [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1]].map(p => coordinate(p[0]!, p[1]!));
  expect(planTerrainCoverage(exact).counts.required).toBe(9);
  expect(planTerrainCoverage([...region].reverse()).counts).toEqual(plan.counts);
});

test("concave region excludes a pixel inside its bounding box but outside its polygon", () => {
  const ring = [[.1, .1], [2.9, .1], [2.9, .9], [.9, .9], [.9, 2.9], [.1, 2.9]]
    .map(([a, b]) => coordinate(x + a!, y + b!));
  const plan = planTerrainCoverage(ring);
  expect(plan.tiles[0]!.pixels).toEqual([0, 1, 2, 256, 512]);
});

test("unbounded, invalid, empty and crossing regions never claim coverage or fetch", async () => {
  const cases: LonLat[][] = [[], [[0, 0], [0, 0], [1, 1]], [[0, 0], [1, 1], [2, 2]],
    [[179, 1], [-179, 1], [179, 2]], [[131, 89], [132, 89], [131, 88]],
    [[131, 31], [132, 31], [131, 32]], [[NaN, 31], [131, 31], [131, 32]],
    [[0, 0], [1, 1], [1, 0], [0, 1]]];
  for (const value of cases) {
    let called = false;
    const result = await acquireTerrainCoverage(value, async () => { called = true; return available(); });
    expect(result.status).toBe("invalid-input");
    expect(called).toBe(false);
  }
});

test("partial DEM coverage retains valid samples without making missing data zero", async () => {
  const inputs: TileInput[] = [available(), { status: "not-acquired", reason: "offline" },
    { status: "missing", reason: "http-404" }, { status: "invalid", reason: "png" }];
  const result = await acquireTerrainCoverage(region, async () => inputs.shift()!);
  expect(result.status).toBe("incomplete");
  expect(result.counts).toEqual({ required: 4, valid: 1, missing: 1, notAcquired: 1, invalid: 1 });
  const nodata = await acquireTerrainCoverage(region, async () => ({ status: "available", elevations: Array(65536).fill(null), provenance }));
  expect(nodata.counts.missing).toBe(4);
  expect(nodata.status).toBe("incomplete");
  const complete = await acquireTerrainCoverage(region, async () => available());
  expect(complete.status).toBe("complete");
  expect(complete.tiles[0]!.input).toMatchObject({ provenance });
});

test("provider exceptions and nonfinite values cannot escape or produce complete coverage", async () => {
  expect((await acquireTerrainCoverage(region, async () => { throw new Error("offline"); })).counts.notAcquired).toBe(4);
  const bad = await acquireTerrainCoverage(region, async () => ({ status: "available", elevations: Array(65536).fill(NaN), provenance }));
  expect(bad.counts.invalid).toBe(4);
  const sparse = await acquireTerrainCoverage(region, async () => ({ status: "available", elevations: Array(65536), provenance }));
  expect(sparse.counts.invalid).toBe(4);
  let calls = 0;
  const cancelled = await acquireTerrainCoverage(region, async () => { calls++; return available(); }, AbortSignal.abort());
  expect(cancelled.counts.notAcquired).toBe(4);
  expect(calls).toBe(0);
});

test("transport caches validated bytes with acquisition provenance and never exposes cache mutation", async () => {
  let requests = 0;
  const source = new GsiDemSource(async (_url, init) => {
    requests++;
    expect(init?.credentials).toBe("omit");
    return new Response(Uint8Array.of(1, 2, 3));
  }, async () => Array(65536).fill(42));
  const first = await source.tile(14174, 6668);
  expect(first.status).toBe("available");
  if (first.status !== "available") return;
  expect(first.provenance.sha256).toBe("039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81");
  first.provenance.source = "modified";
  const second = await source.tile(14174, 6668);
  expect(second).toMatchObject({ status: "available", provenance: { source: "GSI DEM10B PNG" } });
  expect(requests).toBe(1);
});

test("transport distinguishes missing, offline, invalid payload and cancellation; failures are retried", async () => {
  const responses = [new Response(null, { status: 404 }), new Response(null, { status: 503 }), new Response("bad")];
  const source = new GsiDemSource(async () => responses.shift()!, async () => { throw new Error("png"); });
  expect((await source.tile(1, 1)).status).toBe("missing");
  expect((await source.tile(1, 1)).status).toBe("not-acquired");
  expect((await source.tile(1, 1)).status).toBe("invalid");
  expect((await source.tile(1, 1, AbortSignal.abort())).status).toBe("not-acquired");
  expect((await source.tile(-1, 1)).status).toBe("invalid");
});

test("cache expiry, eviction and bounded response reads do not create valid stale or oversized data", async () => {
  const originalNow = Date.now;
  let requests = 0;
  const source = new GsiDemSource(async () => {
    requests++;
    return new Response(Uint8Array.of(1));
  }, async () => Array(65536).fill(1));
  await source.tile(1, 1);
  try {
    Date.now = () => originalNow() + 25 * 60 * 60 * 1000;
    await source.tile(1, 1);
  } finally { Date.now = originalNow; }
  expect(requests).toBe(2);
  for (let x = 2; x <= 17; x++) await source.tile(x, 1);
  await source.tile(1, 1);
  expect(requests).toBe(19);
  let decoded = false;
  const oversized = new GsiDemSource(async () => new Response(new Uint8Array(512 * 1024 + 1)),
    async () => { decoded = true; return []; });
  expect(await oversized.tile(1, 1)).toEqual({ status: "invalid", reason: "payload-size" });
  expect(decoded).toBe(false);
});
