import type { SeaTerrain } from "./sea";
import type { LonLat } from "./terrain";

// A single bounded, disposable snapshot, outside Project/Account Sync and DB versions.
const CACHE = "navmate.terrain.strips-turns.v2";
export const SEA_CACHE_BYTES = 8 * 1024 * 1024;
const MAX_REGIONS = 2048;
export interface SeaRegionEvaluation {
  summary?: SeaTerrain;
  // Successful tiles survive a transport failure in another tile of the same region.
  parts?: Record<string, SeaTerrain>;
}
export const seaRegionKey = (region: readonly LonLat[]) => JSON.stringify(region);

function validTerrain(value: SeaTerrain): boolean {
  if (!value || !value.evaluated || value.not_acquired !== 0 || value.invalid !== 0
    || ![value.required, value.valid, value.missing].every(n => Number.isSafeInteger(n) && n >= 0)
    || value.required <= 0 || value.valid + value.missing !== value.required
    || value.complete !== (value.valid === value.required)
    || (value.valid > 0 ? !Number.isFinite(value.maximum_m) : value.maximum_m !== null)
    || !Array.isArray(value.provenance) || value.provenance.length > 64) return false;
  return value.provenance.every(p => p && [p.source, p.horizontalReference, p.verticalReference,
    p.url, p.acquiredAt, p.sha256].every(s => typeof s === "string") && p.unit === "m");
}
function validEntry(value: SeaRegionEvaluation): boolean {
  return Boolean(value && (value.summary ? validTerrain(value.summary)
    : value.parts && Object.keys(value.parts).length <= 64 && Object.values(value.parts).every(validTerrain)));
}

export class SeaEvaluationCache {
  private readonly entries = new Map<string, { value: SeaRegionEvaluation; bytes: number }>();
  private bytes = 2;
  private loaded?: Promise<void>;
  private saved = Promise.resolve();
  constructor(private readonly persistent = false, private readonly maxBytes = SEA_CACHE_BYTES) {}

  get retainedBytes() { return this.bytes; }
  get size() { return this.entries.size; }

  private async storage(snapshot?: string): Promise<unknown> {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(CACHE, 1);
      let blocked = false;
      request.onupgradeneeded = () => request.result.createObjectStore("evaluation");
      request.onerror = () => reject(request.error);
      request.onblocked = () => { blocked = true; reject(new Error("terrain-cache-blocked")); };
      request.onsuccess = () => {
        if (blocked) { request.result.close(); return; }
        request.result.onversionchange = () => request.result.close();
        resolve(request.result);
      };
    });
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction("evaluation", snapshot === undefined ? "readonly" : "readwrite");
        const store = tx.objectStore("evaluation");
        const request = snapshot === undefined ? store.get("snapshot") : store.put(snapshot, "snapshot");
        tx.oncomplete = () => resolve(request.result);
        tx.onabort = () => reject(tx.error);
        tx.onerror = () => { /* Transaction abort reports the failure. */ };
      });
    } finally { db.close(); }
  }

  ready(): Promise<void> {
    return this.loaded ??= (async () => {
      if (!this.persistent) return;
      try {
        const snapshot = await this.storage();
        if (typeof snapshot !== "string" || new TextEncoder().encode(snapshot).byteLength > this.maxBytes) return;
        const rows: unknown = JSON.parse(snapshot);
        if (!Array.isArray(rows) || rows.length > MAX_REGIONS) return;
        for (const row of rows) {
          if (!Array.isArray(row) || row.length !== 2 || typeof row[0] !== "string"
            || row[0].length > 32768 || !validEntry(row[1])) continue;
          this.set(row[0], row[1]);
        }
      } catch { /* Storage denial/eviction only makes the next evaluation cold. */ }
    })();
  }

  get(key: string): SeaRegionEvaluation | undefined {
    const entry = this.entries.get(key);
    if (entry) { this.entries.delete(key); this.entries.set(key, entry); }
    return entry?.value;
  }

  delete(key: string) {
    const entry = this.entries.get(key);
    if (entry) { this.bytes -= entry.bytes; this.entries.delete(key); }
  }

  set(key: string, value: SeaRegionEvaluation) {
    this.delete(key);
    // Include separators; the serialized snapshot never exceeds this budget.
    const bytes = new TextEncoder().encode(JSON.stringify([key, value])).byteLength + 1;
    if (bytes + 2 > this.maxBytes) return;
    this.entries.set(key, { value, bytes });
    this.bytes += bytes;
    while (this.bytes > this.maxBytes || this.entries.size > MAX_REGIONS) {
      this.delete(this.entries.keys().next().value!);
    }
  }

  flush(): Promise<void> {
    if (!this.persistent) return Promise.resolve();
    this.saved = this.saved.then(async () => {
      try {
        const snapshot = JSON.stringify([...this.entries].map(([key, entry]) => [key, entry.value]));
        await this.storage(snapshot);
      } catch { /* Keep the bounded session cache; never evict Project data. */ }
    });
    return this.saved;
  }
}
