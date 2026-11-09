import { DEM_ZOOM, decodeDemRgba, type TerrainProvenance, type TileInput } from "./terrain";

const MAX_BYTES = 512 * 1024;
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const CACHE_TILES = 16;

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** Decode numeric RGB data, never a rescaled/map-rendered image. */
export async function decodeDemPng(bytes: Uint8Array<ArrayBuffer>): Promise<(number | null)[]> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes.length < 33 || bytes.length > MAX_BYTES ||
      view.getUint32(0) !== 0x89504e47 || view.getUint32(4) !== 0x0d0a1a0a ||
      view.getUint32(8) !== 13 || view.getUint32(12) !== 0x49484452 ||
      view.getUint32(16) !== 256 || view.getUint32(20) !== 256 ||
      bytes[24] !== 8 || bytes[25] !== 2) throw new Error("dem-png-format");
  // Colour profiles are not part of the numeric tile contract. Refuse them rather
  // than allow a canvas colour conversion to silently change encoded elevations.
  let ended = false;
  for (let offset = 8; offset < bytes.length;) {
    if (offset + 12 > bytes.length) throw new Error("dem-png-chunk");
    const length = view.getUint32(offset);
    const name = String.fromCharCode(...bytes.slice(offset + 4, offset + 8));
    if (offset + length + 12 > bytes.length || ["gAMA", "cHRM", "iCCP", "sRGB", "tRNS"].includes(name)) {
      throw new Error("dem-png-chunk");
    }
    if (crc32(bytes.subarray(offset + 4, offset + 8 + length)) !== view.getUint32(offset + 8 + length)) {
      throw new Error("dem-png-crc");
    }
    offset += length + 12;
    if (name === "IEND") {
      if (length !== 0 || offset !== bytes.length) throw new Error("dem-png-end");
      ended = true;
    }
  }
  if (!ended) throw new Error("dem-png-end");
  const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }),
    { colorSpaceConversion: "none", premultiplyAlpha: "none" });
  try {
    if (bitmap.width !== 256 || bitmap.height !== 256) throw new Error("dem-dimensions");
    const context = new OffscreenCanvas(256, 256).getContext("2d", { colorSpace: "srgb" });
    if (!context) throw new Error("dem-decoder-unavailable");
    context.drawImage(bitmap, 0, 0);
    return decodeDemRgba(context.getImageData(0, 0, 256, 256).data);
  } finally { bitmap.close(); }
}

async function readBounded(response: Response): Promise<Uint8Array<ArrayBuffer>> {
  if (!response.body) throw new RangeError("empty-body");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) throw new RangeError("body-budget");
      chunks.push(value);
    }
  } finally { await reader.cancel(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}

/** Disposable, bounded in-memory cache. No IndexedDB, Route, or weather state access.
 * A new instance starts cold; cached bytes are not evidence of current publication.
 */
export class GsiDemSource {
  private readonly cache = new Map<string, { bytes: Uint8Array<ArrayBuffer>; provenance: TerrainProvenance }>();
  constructor(
    private readonly fetcher: typeof fetch = fetch,
    private readonly decode: typeof decodeDemPng = decodeDemPng,
  ) {}

  async tile(x: number, y: number, signal?: AbortSignal): Promise<TileInput> {
    if (![x, y].every(v => Number.isInteger(v) && v >= 0 && v < 2 ** DEM_ZOOM)) {
      return { status: "invalid", reason: "tile-coordinate" };
    }
    if (signal?.aborted) return { status: "not-acquired", reason: "cancelled" };
    const url = `https://cyberjapandata.gsi.go.jp/xyz/dem_png/${DEM_ZOOM}/${x}/${y}.png`;
    const cached = this.cache.get(url);
    if (cached && Date.now() - Date.parse(cached.provenance.acquiredAt) < CACHE_TTL_MS) {
      try {
        return { status: "available", elevations: await this.decode(cached.bytes.slice()),
          provenance: { ...cached.provenance } };
      } catch { this.cache.delete(url); }
    } else this.cache.delete(url);
    let bytes: Uint8Array<ArrayBuffer>;
    try {
      const response = await this.fetcher(url, { credentials: "omit", redirect: "error", cache: "no-cache",
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10_000)]) : AbortSignal.timeout(10_000) });
      if (!response.ok) {
        await response.body?.cancel();
        return { status: response.status === 404 ? "missing" : "not-acquired", reason: `http-${response.status}` };
      }
      bytes = await readBounded(response);
    } catch (error) { return error instanceof RangeError ? { status: "invalid", reason: "payload-size" }
      : { status: "not-acquired", reason: "transport-failed" }; }
    try {
      const elevations = await this.decode(bytes.slice());
      if (elevations.length !== 65536 || Array.from(elevations).some(v => v !== null && !Number.isFinite(v))) {
        throw new Error("dem-values");
      }
      const sha256 = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
        .map(value => value.toString(16).padStart(2, "0")).join("");
      const provenance: TerrainProvenance = { source: "GSI DEM10B PNG", unit: "m", url,
        horizontalReference: "Web Mercator XYZ / longitude-latitude",
        verticalReference: "GSI published elevation (TP; island local datums may apply; epoch unspecified)",
        acquiredAt: new Date().toISOString(), sha256 };
      this.cache.set(url, { bytes, provenance });
      while (this.cache.size > CACHE_TILES) this.cache.delete(this.cache.keys().next().value!);
      return { status: "available", elevations, provenance: { ...provenance } };
    } catch { return { status: "invalid", reason: "dem-payload" }; }
  }
}
