/** Terrain input only. No SEA calculation, Project mutation or weather fallback. */
export const DEM_ZOOM = 14;
export const TILE_SIZE = 256;
const WORLD = TILE_SIZE * 2 ** DEM_ZOOM;
const LAT_LIMIT = 85.0511287798066;
const EPS = 1e-7; // Sub-pixel tolerance; include both sides of a raster boundary.
export type LonLat = readonly [longitude: number, latitude: number];
type XY = readonly [x: number, y: number];

export interface TerrainProvenance {
  source: string;
  horizontalReference: string;
  verticalReference: string;
  unit: "m";
  url: string;
  acquiredAt: string;
  sha256: string;
}
export type TileInput =
  | { status: "available"; elevations: readonly (number | null)[]; provenance: TerrainProvenance }
  | { status: "not-acquired" | "missing" | "invalid"; reason: string };
export interface TerrainTile {
  x: number;
  y: number;
  /** Row-major indices of every pixel whose closed footprint meets the polygon. */
  pixels: number[];
  input: TileInput;
}
export interface TerrainCoverage {
  status: "complete" | "incomplete" | "invalid-input";
  reason?: string;
  zoom: typeof DEM_ZOOM;
  region: LonLat[];
  tiles: TerrainTile[];
  counts: { required: number; valid: number; missing: number; notAcquired: number; invalid: number };
}

export function projectTerrainCoordinate([lon, lat]: LonLat): XY {
  return [(lon + 180) / 360 * WORLD,
    (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * WORLD];
}

function cross(a: XY, b: XY, c: XY): number {
  return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}
function onSegment(a: XY, b: XY, p: XY): boolean {
  return Math.abs(cross(a, b, p)) <= EPS &&
    p[0] >= Math.min(a[0], b[0]) - EPS && p[0] <= Math.max(a[0], b[0]) + EPS &&
    p[1] >= Math.min(a[1], b[1]) - EPS && p[1] <= Math.max(a[1], b[1]) + EPS;
}
function intersects(a: XY, b: XY, c: XY, d: XY): boolean {
  return (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0) ||
    onSegment(a, b, c) || onSegment(a, b, d) || onSegment(c, d, a) || onSegment(c, d, b);
}
function contains(ring: readonly XY[], p: XY): boolean {
  let inside = false;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!, b = ring[(i + 1) % ring.length]!;
    if (onSegment(a, b, p)) return true;
    if ((a[1] > p[1]) !== (b[1] > p[1]) &&
        p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

/** Point sources are supplemental observations, never proof of area coverage. */
export function terrainContainsPoint(coverage: TerrainCoverage, point: LonLat): boolean {
  if (coverage.status === "invalid-input" || !point.every(Number.isFinite) ||
      Math.abs(point[0]) >= 180 || Math.abs(point[1]) >= LAT_LIMIT) return false;
  return contains(coverage.region.map(projectTerrainCoordinate), projectTerrainCoordinate(point));
}
function touchesPixel(ring: readonly XY[], x: number, y: number): boolean {
  const corners: XY[] = [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1]];
  if (corners.some(p => contains(ring, p))) return true;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!, b = ring[(i + 1) % ring.length]!;
    if (a[0] >= x && a[0] <= x + 1 && a[1] >= y && a[1] <= y + 1) return true;
    if (corners.some((c, j) => intersects(a, b, c, corners[(j + 1) % 4]!))) return true;
  }
  return false;
}

/** Simple open ring, straight edges in Web Mercator. Caller constructs the evaluation area.
 * No holes or antimeridian wrapping. Invalid/budget-exceeding areas never become complete.
 */
export function planTerrainCoverage(region: readonly LonLat[]): TerrainCoverage {
  const result: TerrainCoverage = { status: "invalid-input", zoom: DEM_ZOOM,
    region: region.map(p => [...p]), tiles: [],
    counts: { required: 0, valid: 0, missing: 0, notAcquired: 0, invalid: 0 } };
  const invalid = (reason: string) => ({ ...result, reason });
  if (region.length < 3 || region.length > 128 || region.some(p => p.length !== 2 ||
      !Number.isFinite(p[0]) || !Number.isFinite(p[1]) || Math.abs(p[0]) >= 180 ||
      Math.abs(p[1]) >= LAT_LIMIT)) return invalid("coordinates");
  if (Math.max(...region.map(p => p[0])) - Math.min(...region.map(p => p[0])) >= 180) {
    return invalid("antimeridian");
  }
  const ring = region.map(projectTerrainCoordinate);
  let area = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!, b = ring[(i + 1) % ring.length]!;
    if (Math.hypot(a[0] - b[0], a[1] - b[1]) < EPS) return invalid("duplicate-vertex");
    area += cross(ring[0]!, a, b);
    for (let j = i + 1; j < ring.length; j++) {
      if (j === i + 1 || (i === 0 && j === ring.length - 1)) continue;
      if (intersects(a, b, ring[j]!, ring[(j + 1) % ring.length]!)) return invalid("self-intersection");
    }
  }
  if (Math.abs(area) < EPS) return invalid("empty-region");
  const minX = Math.max(0, Math.floor(Math.min(...ring.map(p => p[0])) - EPS));
  const maxX = Math.min(WORLD - 1, Math.floor(Math.max(...ring.map(p => p[0])) + EPS));
  const minY = Math.max(0, Math.floor(Math.min(...ring.map(p => p[1])) - EPS));
  const maxY = Math.min(WORLD - 1, Math.floor(Math.max(...ring.map(p => p[1])) + EPS));
  const tileCount = (Math.floor(maxX / 256) - Math.floor(minX / 256) + 1) *
    (Math.floor(maxY / 256) - Math.floor(minY / 256) + 1);
  if (tileCount > 64) return invalid("tile-budget");
  const tiles = new Map<string, TerrainTile>();
  for (let y = minY; y <= maxY; y++) for (let x = minX; x <= maxX; x++) {
    if (!touchesPixel(ring, x, y)) continue;
    const tx = Math.floor(x / 256), ty = Math.floor(y / 256), key = `${tx}/${ty}`;
    let tile = tiles.get(key);
    if (!tile) {
      tile = { x: tx, y: ty, pixels: [], input: { status: "not-acquired", reason: "not-requested" } };
      tiles.set(key, tile);
    }
    tile.pixels.push((y % 256) * 256 + x % 256);
    result.counts.required++;
  }
  result.tiles = [...tiles.values()];
  result.counts.notAcquired = result.counts.required;
  result.status = "incomplete";
  return result;
}

/** Signed 24-bit centimetres; the reserved midpoint is missing, never sea level. */
export function decodeDemRgba(rgba: Uint8ClampedArray): (number | null)[] {
  if (rgba.length !== 256 * 256 * 4) throw new Error("dem-dimensions");
  return Array.from({ length: 256 * 256 }, (_, i) => {
    const offset = i * 4;
    if (rgba[offset + 3] !== 255) throw new Error("dem-alpha");
    const value = rgba[offset]! * 65536 + rgba[offset + 1]! * 256 + rgba[offset + 2]!;
    return value === 8388608 ? null : (value > 8388608 ? value - 16777216 : value) / 100;
  });
}

export async function acquireTerrainCoverage(
  region: readonly LonLat[],
  load: (x: number, y: number, signal: AbortSignal) => Promise<TileInput>,
  signal: AbortSignal = AbortSignal.timeout(60_000),
): Promise<TerrainCoverage> {
  const result = planTerrainCoverage(region);
  if (result.status === "invalid-input") return result;
  result.counts.notAcquired = 0;
  for (const tile of result.tiles) {
    try { tile.input = signal.aborted ? { status: "not-acquired", reason: "cancelled" }
      : await load(tile.x, tile.y, signal); }
    catch { tile.input = { status: "not-acquired", reason: "transport-failed" }; }
    if (tile.input.status === "available" && (tile.input.elevations.length !== 65536 ||
        Array.from(tile.input.elevations).some(v => v !== null && !Number.isFinite(v)))) {
      tile.input = { status: "invalid", reason: "dem-values" };
    }
    if (tile.input.status === "available") {
      for (const pixel of tile.pixels) {
        if (tile.input.elevations[pixel] === null) result.counts.missing++;
        else result.counts.valid++;
      }
    } else {
      const key = tile.input.status === "not-acquired" ? "notAcquired" : tile.input.status;
      result.counts[key] += tile.pixels.length;
    }
  }
  result.status = result.counts.required > 0 && result.counts.valid === result.counts.required
    ? "complete" : "incomplete";
  return result;
}
