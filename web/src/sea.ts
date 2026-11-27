import { planSeaTerrainCoverage, type LonLat, type TerrainProvenance, type TileInput } from "./terrain";
import { GsiDemSource } from "./terrainTransport";
import type { TerrainKmlInput } from "./terrainKml";
import { SeaEvaluationCache, seaRegionKey } from "./seaCache";

export interface SeaTerrain {
  complete: boolean;
  evaluated?: boolean;
  maximum_m: number | null;
  required: number;
  valid: number;
  missing: number;
  not_acquired: number;
  invalid: number;
  provenance: TerrainProvenance[];
}
export interface SeaInterval {
  key: string;
  section_id: string;
  from_id: string;
  to_id: string;
  from_name: string;
  to_name: string;
  coordinates: LonLat[];
  geometry_valid: boolean;
  regions?: LonLat[][];
  automatic_ft: number | null;
  reference?: boolean;
  manual_ft: number | null;
  value_ft: number | null;
  status: "manual" | "automatic" | "unknown";
  warning: "below-automatic" | "unconfirmed" | null;
  terrain: SeaTerrain;
}
export interface SeaPlan {
  geometry_key: string;
  intervals: SeaInterval[];
  kml_source?: { source: string; verticalReference: string; demCompatibilityEvidence: string; importedAt: string; sha256: string } | null;
}
export interface SeaUpdate {
  project_id: string;
  geometry_key: string;
  terrain?: Record<string, SeaTerrain>;
  manual?: Record<string, number | null>;
  kml?: TerrainKmlInput;
}

export const seaNeedsEvaluation = (terrain: SeaTerrain) =>
  !(terrain.complete || terrain.evaluated) || terrain.required === 0 || terrain.not_acquired > 0 || terrain.invalid > 0;

const emptyTerrain = (evaluated = true): SeaTerrain => ({ complete: evaluated, evaluated,
  maximum_m: null, required: 0, valid: 0, missing: 0, not_acquired: 0, invalid: 0, provenance: [] });

function combine(parts: SeaTerrain[]): SeaTerrain {
  const result = emptyTerrain(parts.length > 0);
  const provenance = new Map<string, TerrainProvenance>();
  for (const part of parts) {
    result.complete &&= part.complete;
    result.evaluated &&= part.evaluated === true;
    for (const field of ["required", "valid", "missing", "not_acquired", "invalid"] as const) result[field] += part[field];
    if (part.maximum_m !== null) result.maximum_m = Math.max(result.maximum_m ?? -Infinity, part.maximum_m);
    for (const item of part.provenance) provenance.set(item.url, item);
  }
  result.provenance = [...provenance.values()];
  return result;
}

export interface SeaEvaluationMetrics {
  tileRequests: number;
  regionEvaluations: number;
  regionHits: number;
  evaluatedPixels: number;
}

/** Evaluate reusable strips/sectors independently, then aggregate exact CP intervals. */
export async function acquireSea(
  plan: SeaPlan, signal: AbortSignal,
  source: Pick<GsiDemSource, "tile"> = new GsiDemSource(),
  options: {
    cache?: SeaEvaluationCache;
    force?: boolean;
    onInterval?: (key: string, terrain: SeaTerrain) => Promise<void>;
    metrics?: SeaEvaluationMetrics;
  } = {},
): Promise<Record<string, SeaTerrain>> {
  const result: Record<string, SeaTerrain> = {};
  const cache = options.cache ?? new SeaEvaluationCache();
  await cache.ready();
  if (options.force) for (const interval of plan.intervals) {
    for (const region of interval.regions ?? []) cache.delete(seaRegionKey(region));
  }
  const tiles = new Map<string, TileInput>();
  const failures = new Map<string, number>();
  const load = async (x: number, y: number): Promise<TileInput> => {
    const key = `${x}/${y}`;
    if ((failures.get(key) ?? 0) >= 3) return { status: "not-acquired", reason: "retries-exhausted" };
    let tile = tiles.get(key);
    if (!tile) {
      if (options.metrics) options.metrics.tileRequests++;
      try { tile = await source.tile(x, y, signal); }
      catch { tile = { status: "not-acquired", reason: "transport-failed" }; }
      if (tile.status === "not-acquired") failures.set(key, (failures.get(key) ?? 0) + 1);
      if (tile.status === "available" && (tile.elevations.length !== 65536
        || Array.from(tile.elevations).some(v => v !== null && !Number.isFinite(v)))) {
        tile = { status: "invalid", reason: "dem-values" };
      }
      // A failed request must not poison a later attempt. Missing DEM is evaluated data.
      if (tile.status !== "not-acquired") {
        tiles.set(key, tile);
        if (tiles.size > 32) tiles.delete(tiles.keys().next().value!);
      }
    }
    return tile;
  };

  const evaluate = async (region: LonLat[]): Promise<SeaTerrain> => {
    const key = seaRegionKey(region), cached = cache.get(key);
    if (cached?.summary) {
      if (options.metrics) options.metrics.regionHits++;
      return cached.summary;
    }
    if (signal.aborted) return emptyTerrain(false);
    // Yield between raster plans, including warm aggregation, for input and cancellation.
    await new Promise<void>(resolve => setTimeout(resolve, 0));
    if (signal.aborted) return emptyTerrain(false);
    const coverage = await planSeaTerrainCoverage(region, signal);
    if (options.metrics) options.metrics.regionEvaluations++;
    if (!coverage || coverage.status === "invalid-input") return emptyTerrain(false);
    const retained = { ...cached?.parts };
    const parts: SeaTerrain[] = [];
    let sliceStart = performance.now();
    for (const tile of coverage.tiles) {
      // Cached tiles can resolve entirely in microtasks, including their pixel scans.
      if (performance.now() - sliceStart >= 5) {
        await new Promise<void>(resolve => setTimeout(resolve, 0));
        sliceStart = performance.now();
      }
      const tileKey = `${tile.x}/${tile.y}`;
      if (retained[tileKey]) { parts.push(retained[tileKey]!); continue; }
      let input: TileInput = { status: "not-acquired", reason: "cancelled" };
      for (let attempt = 0; attempt < 3 && !signal.aborted; attempt++) {
        if (attempt) await new Promise<void>(resolve => setTimeout(resolve, 250 * attempt));
        if (signal.aborted) break;
        input = await load(tile.x, tile.y);
        if (input.status !== "not-acquired" || (failures.get(tileKey) ?? 0) >= 3) break;
      }
      const part = emptyTerrain();
      part.required = tile.pixels.length;
      if (input.status === "available") {
        part.provenance = [input.provenance];
        for (const pixel of tile.pixels) {
          const value = input.elevations[pixel]!;
          if (value === null) part.missing++;
          else { part.valid++; part.maximum_m = Math.max(part.maximum_m ?? -Infinity, value); }
        }
        if (options.metrics) options.metrics.evaluatedPixels += tile.pixels.length;
      } else part[input.status === "not-acquired" ? "not_acquired" : input.status] = part.required;
      part.complete = part.valid === part.required;
      if (signal.aborted) part.evaluated = false;
      parts.push(part);
      if (part.evaluated && !part.not_acquired && !part.invalid) retained[tileKey] = part;
    }
    const summary = combine(parts);
    if (summary.evaluated && !summary.not_acquired && !summary.invalid) cache.set(key, { summary });
    else if (Object.keys(retained).length) cache.set(key, { parts: retained });
    return summary;
  };
  try {
    for (const interval of plan.intervals) {
      if (!options.force && interval.terrain && !seaNeedsEvaluation(interval.terrain)) continue;
      const parts: SeaTerrain[] = [];
      for (const region of interval.geometry_valid ? interval.regions ?? [] : []) parts.push(await evaluate(region));
      const summary = combine(parts);
      result[interval.key] = summary;
      await options.onInterval?.(interval.key, summary);
      await new Promise<void>(resolve => setTimeout(resolve, 0));
    }
    return result;
  } finally { await cache.flush(); }
}
