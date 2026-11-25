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

test("SEA combines all strips, retains provenance, and any missing strip prevents confirmation", async () => {
  const { acquireSea } = await import("../src/sea");
  const interval = { key: "section-a", geometry_valid: true, regions: [region, region] } as import("../src/sea").SeaInterval;
  const plan = { geometry_key: "fixture", intervals: [interval] };
  let calls = 0;
  const source = { tile: async (): Promise<TileInput> => { calls++; return available(); } };
  const result = await acquireSea(plan, new AbortController().signal, source);
  expect(result[interval.key]).toMatchObject({ complete: true, maximum_m: 100, required: 8, valid: 8 });
  expect(result[interval.key]!.provenance).toEqual([provenance]);
  expect(calls).toBe(4); // Adjacent strips reuse validated inputs.
  const missing = await acquireSea(plan, new AbortController().signal, {
    tile: async (x): Promise<TileInput> => x === 14173 ? available() : { status: "missing", reason: "404" },
  });
  expect(missing[interval.key]).toMatchObject({ complete: false, maximum_m: 100, missing: 4, evaluated: true });
  const cancelled = await acquireSea(plan, AbortSignal.abort(), source);
  expect(cancelled[interval.key]!.complete).toBe(false);
  expect(cancelled[interval.key]!.maximum_m).toBeNull();
});

test("#496 missing strips do not hide a later maximum; failures and cancellation stay distinct", async () => {
  const { acquireSea } = await import("../src/sea");
  const later = region.map(([lon, lat]) => [lon + 360 / 16384 * 3, lat] as LonLat);
  const interval = { key: "coastal", geometry_valid: true, regions: [region, later] } as import("../src/sea").SeaInterval;
  const plan = { geometry_key: "fixture", intervals: [interval] };
  for (const failure of ["missing", "not-acquired", "invalid"] as const) {
    const result = (await acquireSea(plan, new AbortController().signal, {
      tile: async (tx): Promise<TileInput> => tx < 14175 ? { status: failure, reason: "fixture" }
        : { status: "available", elevations: Array(65536).fill(900), provenance },
    }))[interval.key]!;
    expect(result).toMatchObject({ complete: false, evaluated: true, maximum_m: 900, required: 8, valid: 4 });
    expect(result[failure === "not-acquired" ? "not_acquired" : failure]).toBe(4);
  }
  const invalid = { ...interval, regions: [region, []] };
  expect((await acquireSea({ ...plan, intervals: [invalid] }, new AbortController().signal,
    { tile: async () => available() }))[interval.key]).toMatchObject({ complete: false, evaluated: false });
  const cancelled = new AbortController();
  const result = await acquireSea(plan, cancelled.signal, {
    tile: async () => { cancelled.abort(); return available(); },
  });
  expect(result[interval.key]!.evaluated).toBe(false);
});

test("#526 convex scan bands match independent polygon-square separating axes", () => {
  const polygons = [
    [[0, 0], [5, 0], [0, 5]], [[.1, .2], [7.1, 3.2], [6.1, 5.2], [-.9, 2.2]],
    [[0, 0], [0, 5], [-5, 5], [-5, 0]], [[.2, .2], [.2001, .2], [.2001, 5], [.2, 5]],
    [[0, 0], [4, 0], [3, 3], [0, 4]],
  ];
  for (const vertices of polygons) for (const shift of [0, .25, -.25]) {
    const polygon = vertices.map(([a, b]) => [a! + shift, b! + shift]);
    const axes = [[1, 0], [0, 1], ...polygon.map((p, i) => {
      const q = polygon[(i + 1) % polygon.length]!;
      return [p[1]! - q[1]!, q[0]! - p[0]!];
    })];
    const expected: string[] = [];
    for (let yy = -7; yy <= 8; yy++) for (let xx = -7; xx <= 8; xx++) {
      const square = [[xx, yy], [xx + 1, yy], [xx + 1, yy + 1], [xx, yy + 1]];
      const touches = axes.every(([a, b]) => {
        const one = polygon.map(p => p[0]! * a! + p[1]! * b!);
        const two = square.map(p => p[0]! * a! + p[1]! * b!);
        return Math.min(...one) <= Math.max(...two) + 1e-7 && Math.min(...two) <= Math.max(...one) + 1e-7;
      });
      if (touches) expected.push(`${xx}/${yy}`);
    }
    const plan = planTerrainCoverage(polygon.map(([a, b]) => coordinate(x + a!, y + b!)));
    const actual = plan.tiles.flatMap(t => t.pixels.map(p => `${t.x * 256 + p % 256 - x}/${t.y * 256 + Math.floor(p / 256) - y}`));
    expect(actual.sort()).toEqual(expected.sort());
  }
});

test("#526 CP boundaries reuse common regions, exclude outside peaks and match a cold evaluation", async () => {
  const { acquireSea } = await import("../src/sea");
  const { SeaEvaluationCache } = await import("../src/seaCache");
  const strip = (left: number, right: number) => [[left, .2], [right, .2], [right, 2.8], [left, 2.8]]
    .map(([a, b]) => coordinate(x + a!, y + b!));
  const interval = (key: string, regions: LonLat[][]) => ({ key, geometry_valid: true, regions } as import("../src/sea").SeaInterval);
  const plan = (intervals: import("../src/sea").SeaInterval[]) => ({ geometry_key: "fixture", intervals });
  const metrics = () => ({ tileRequests: 0, regionEvaluations: 0, regionHits: 0, evaluatedPixels: 0 });
  const cache = new SeaEvaluationCache();
  const elevations = Array(65536).fill(1); elevations[5] = 900;
  const source = { tile: async (): Promise<TileInput> => ({ status: "available", elevations, provenance }) };
  const signal = new AbortController().signal;
  const full = plan([interval("all", [strip(.2, 3), strip(3, 6), strip(6, 9.8)])]);
  const first = metrics();
  expect((await acquireSea(full, signal, source, { cache, metrics: first })).all!.maximum_m).toBe(900);
  expect(first.regionEvaluations).toBe(3);
  for (const boundary of [4.1, 4.6]) {
    const split = plan([interval("before", [strip(.2, 3), strip(3, boundary)]),
      interval("after", [strip(boundary, 6), strip(6, 9.8)])]);
    const edited = metrics();
    const warm = await acquireSea(split, signal, source, { cache, metrics: edited });
    const cold = await acquireSea(split, signal, source);
    expect(warm).toEqual(cold);
    expect(warm.before!.maximum_m).toBe(1);
    expect(warm.after!.maximum_m).toBe(900);
    expect(edited.regionEvaluations).toBe(2);
    expect(edited.regionHits).toBe(2);
    expect(edited.evaluatedPixels).toBeLessThan(first.evaluatedPixels);
  }
  const removed = metrics();
  await acquireSea(full, signal, source, { cache, metrics: removed });
  expect(removed).toEqual({ tileRequests: 0, regionEvaluations: 0, regionHits: 3, evaluatedPixels: 0 });
});

test("#526 completed intervals publish independently; shared sectors evaluate once and manual refresh is cold", async () => {
  const { acquireSea } = await import("../src/sea");
  const { SeaEvaluationCache } = await import("../src/seaCache");
  const cache = new SeaEvaluationCache();
  const later = region.map(([lon, lat]) => [lon + 360 / 16384 * 3, lat] as LonLat);
  const plan = { geometry_key: "fixture", intervals: [
    { key: "a", geometry_valid: true, regions: [region] },
    { key: "b", geometry_valid: true, regions: [region, later] },
  ] as import("../src/sea").SeaInterval[] };
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let waiting!: () => void;
  const started = new Promise<void>(resolve => { waiting = resolve; });
  const published: string[] = [];
  const metrics = { tileRequests: 0, regionEvaluations: 0, regionHits: 0, evaluatedPixels: 0 };
  const running = acquireSea(plan, new AbortController().signal, { tile: async tx => {
    if (tx > 14174) { waiting(); await held; }
    return available();
  } }, { cache, metrics, onInterval: async key => { published.push(key); } });
  await started;
  expect(published).toEqual(["a"]);
  release();
  const result = await running;
  expect(published).toEqual(["a", "b"]);
  expect(metrics.regionEvaluations).toBe(2);
  expect(metrics.regionHits).toBe(1);
  const saved = { ...plan, intervals: plan.intervals.map(i => ({ ...i, terrain: result[i.key]! })) };
  let calls = 0;
  const source = { tile: async () => { calls++; return available(); } };
  expect(await acquireSea(saved, new AbortController().signal, source, { cache })).toEqual({});
  expect(calls).toBe(0);
  await acquireSea(saved, new AbortController().signal, source, { cache, force: true });
  expect(calls).toBeGreaterThan(0);
});

test("#526 finite transport retries preserve evaluated tiles and never retry DEM missing values", async () => {
  const { acquireSea, seaNeedsEvaluation } = await import("../src/sea");
  const { SeaEvaluationCache } = await import("../src/seaCache");
  const cache = new SeaEvaluationCache();
  const plan = { geometry_key: "fixture", intervals: [
    { key: "a", geometry_valid: true, regions: [region, region] },
  ] as import("../src/sea").SeaInterval[] };
  const requests = new Map<string, number>();
  let fail = true;
  const source = { tile: async (tx: number, ty: number): Promise<TileInput> => {
    const key = `${tx}/${ty}`;
    requests.set(key, (requests.get(key) ?? 0) + 1);
    if (tx === 14173) return { status: "missing", reason: "404" };
    if (ty === 6668 && fail) throw new Error("timeout");
    return available();
  } };
  const first = (await acquireSea(plan, new AbortController().signal, source, { cache })).a!;
  expect(first).toMatchObject({ valid: 2, missing: 4, not_acquired: 2, complete: false });
  expect([...requests.values()].sort()).toEqual([1, 1, 1, 3]);
  expect(seaNeedsEvaluation(first)).toBe(true);
  requests.clear(); fail = false;
  const second = (await acquireSea(plan, new AbortController().signal, source, { cache })).a!;
  expect(second).toMatchObject({ valid: 4, missing: 4, not_acquired: 0, evaluated: true });
  expect([...requests.values()]).toEqual([1]);
  expect(seaNeedsEvaluation(second)).toBe(false);
});

test("#526 region cache has finite byte and entry budgets and eviction only loses reuse", async () => {
  const { SeaEvaluationCache } = await import("../src/seaCache");
  const cache = new SeaEvaluationCache(false, 1500);
  const summary = { complete: true, evaluated: true, maximum_m: 10, required: 1, valid: 1,
    missing: 0, not_acquired: 0, invalid: 0, provenance: [] };
  for (let i = 0; i < 100; i++) cache.set(String(i), { summary });
  expect(cache.retainedBytes).toBeLessThanOrEqual(1500);
  expect(cache.size).toBeLessThan(100);
  expect(cache.get("0")).toBeUndefined();
  expect(cache.get("99")?.summary).toEqual(summary);
});
