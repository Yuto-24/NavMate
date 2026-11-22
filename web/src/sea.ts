import { acquireTerrainCoverage, type LonLat, type TerrainProvenance, type TileInput } from "./terrain";
import { GsiDemSource } from "./terrainTransport";
import type { TerrainKmlInput } from "./terrainKml";

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

/** Aggregate every strip, retaining missing coverage separately from evaluation completion.
 * Reuse the #313 decoder/coverage contract, with a bounded per-request tile cache.
 */
export async function acquireSea(
  plan: SeaPlan, signal: AbortSignal,
  source: Pick<GsiDemSource, "tile"> = new GsiDemSource(),
): Promise<Record<string, SeaTerrain>> {
  const result: Record<string, SeaTerrain> = {};
  const cache = new Map<string, TileInput>();
  const load = async (x: number, y: number, requestSignal: AbortSignal): Promise<TileInput> => {
    const key = `${x}/${y}`;
    let tile = cache.get(key);
    if (!tile) {
      tile = await source.tile(x, y, requestSignal);
      cache.set(key, tile);
      if (cache.size > 64) cache.delete(cache.keys().next().value!);
    }
    return tile;
  };
  for (const interval of plan.intervals) {
    const summary: SeaTerrain = { complete: Boolean(interval.geometry_valid && interval.regions?.length),
      evaluated: Boolean(interval.geometry_valid && interval.regions?.length),
      maximum_m: null, required: 0, valid: 0, missing: 0, not_acquired: 0, invalid: 0, provenance: [] };
    const provenance = new Map<string, TerrainProvenance>();
    for (const region of interval.regions ?? []) {
      if (signal.aborted) { summary.complete = false; summary.evaluated = false; break; }
      // Yield between synchronous raster plans so cancel and the rest of NAVLOG stay responsive.
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      const coverage = await acquireTerrainCoverage(region, load, signal);
      summary.complete &&= coverage.status === "complete";
      summary.required += coverage.counts.required;
      summary.valid += coverage.counts.valid;
      summary.missing += coverage.counts.missing;
      summary.not_acquired += coverage.counts.notAcquired;
      summary.invalid += coverage.counts.invalid;
      for (const tile of coverage.tiles) {
        if (tile.input.status !== "available") continue;
        provenance.set(tile.input.provenance.url, tile.input.provenance);
        for (const pixel of tile.pixels) {
          const elevation = tile.input.elevations[pixel];
          if (elevation != null) summary.maximum_m = Math.max(summary.maximum_m ?? -Infinity, elevation);
        }
      }
      if (coverage.status === "invalid-input" || signal.aborted) summary.evaluated = false;
    }
    summary.provenance = [...provenance.values()];
    result[interval.key] = summary;
  }
  return result;
}
