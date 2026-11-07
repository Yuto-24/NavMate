/** Static prepared-data transport. No model, Run-selection or interpolation rules. */
export class WeatherError extends Error {
  constructor(readonly code: string, message: string) { super(message); }
}

export interface PreparedAsset { file: string; sha256: string; bytes: number; run: string }
const CACHE = "autonavlog.weather.msm.v1";
const PAYLOAD_TTL = 7 * 24 * 60 * 60_000;
const MAX_PAYLOAD = 32 * 1024 * 1024;
const MAX_CACHE = 128 * 1024 * 1024;

export class LocalWeatherTransport {
  constructor(
    private readonly base = new URL(`${import.meta.env.BASE_URL}weather/msm/`, self.location.origin),
    private readonly cacheName = CACHE,
  ) {}

  private async cache(): Promise<Cache | undefined> {
    try { return await caches.open(this.cacheName); } catch { return undefined; }
  }

  private async cached(url: URL, ttl: number): Promise<Response | undefined> {
    try {
      const cache = await this.cache();
      const response = await cache?.match(url);
      if (!response) return undefined;
      const age = Date.now() - Number(response.headers.get("X-AutoNavLog-Cached-At"));
      if (!Number.isFinite(age) || age < 0 || age >= ttl) {
        await cache?.delete(url);
        return undefined;
      }
      return response;
    } catch { return undefined; }
  }

  private async remove(url: URL) {
    try { await (await this.cache())?.delete(url); } catch { /* disposable */ }
  }

  private async store(url: URL, bytes: Uint8Array, cachedAt = Date.now()) {
    try {
      const cache = await this.cache();
      if (!cache) return;
      let total = bytes.byteLength;
      const entries = [];
      for (const key of await cache.keys()) {
        const entry = await cache.match(key);
        const size = Number(entry?.headers.get("Content-Length"));
        if (!Number.isFinite(size) || size < 0) { await cache.delete(key); continue; }
        total += size;
        entries.push({ key, size });
      }
      // Cache API key order is insertion order; discard oldest disposable data first.
      for (const entry of entries) {
        if (total <= MAX_CACHE) break;
        await cache.delete(entry.key);
        total -= entry.size;
      }
      await cache.put(url, new Response(bytes.slice().buffer, { headers: {
        "Content-Length": String(bytes.byteLength), "X-AutoNavLog-Cached-At": String(cachedAt),
      } }));
    } catch { /* Quota/denial affects warm reuse, never Project data or a valid result. */ }
  }

  private async read(response: Response, limit: number): Promise<Uint8Array> {
    if (Number(response.headers.get("Content-Length")) > limit) {
      await response.body?.cancel();
      throw new WeatherError("WEATHER_DOWNLOAD_FAILED", "予報配信データがサイズ上限を超えています。");
    }
    const reader = response.body?.getReader();
    if (!reader) throw new WeatherError("WEATHER_DOWNLOAD_FAILED", "予報応答本文がありません。");
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        size += next.value.byteLength;
        if (size > limit) {
          await reader.cancel();
          throw new WeatherError("WEATHER_DOWNLOAD_FAILED", "予報配信データがサイズ上限を超えています。");
        }
        chunks.push(next.value);
      }
    } catch (error) {
      if (error instanceof WeatherError) throw error;
      throw new WeatherError("WEATHER_TRANSPORT_FAILED", "予報データのdownloadを完了できません。");
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return bytes;
  }

  private async download(url: URL, limit: number, catalog: boolean): Promise<Uint8Array> {
    let response: Response;
    try {
      response = await fetch(url, { cache: "no-cache", credentials: "omit", redirect: "error",
        signal: AbortSignal.timeout(60_000) });
    } catch {
      throw new WeatherError("WEATHER_COMMUNICATION_FAILED", "予報配信元へ接続できません。");
    }
    if (!response.ok) {
      await response.body?.cancel();
      throw new WeatherError(catalog ? "WEATHER_DISCOVERY_FAILED"
        : response.status === 404 || response.status === 503 ? "WEATHER_SOURCE_UNAVAILABLE"
        : "WEATHER_TRANSPORT_FAILED", `予報取得に失敗しました（HTTP ${response.status}）。`);
    }
    return this.read(response, limit);
  }

  async catalog<T>(accept: (text: string, current: boolean) => T): Promise<T> {
    const url = new URL("catalog.json", this.base);
    const previousUrl = new URL("catalog.previous.json", this.base);
    // Keep two validated catalog snapshots within the same bounded disposable cache.
    // Each action checks the server; cached catalogs are acquisition candidates only.
    const snapshots: { url: URL; bytes: Uint8Array; text: string; cachedAt: number }[] = [];
    for (const location of [url, previousUrl]) {
      const response = await this.cached(location, PAYLOAD_TTL);
      if (!response) continue;
      try {
        const bytes = await this.read(response, 4 * 1024 * 1024);
        const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        JSON.parse(text);
        snapshots.push({ url: location, bytes, text,
          cachedAt: Number(response.headers.get("X-AutoNavLog-Cached-At")) });
      } catch { await this.remove(location); }
    }
    let result: T | undefined;
    let accepted = false;
    let serverText: string | undefined;
    let serverBytes: Uint8Array | undefined;
    let retained: (typeof snapshots)[number] | undefined;
    let failure: unknown;
    try {
      const bytes = await this.download(url, 4 * 1024 * 1024, true);
      let text: string;
      try { text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); JSON.parse(text); }
      catch { throw new WeatherError("WEATHER_CATALOG_INVALID", "予報配信情報を読み取れません。"); }
      result = accept(text, true); // Python validates before any cache replacement.
      accepted = true;
      serverText = text;
      serverBytes = bytes;
    } catch (error) {
      if (!(error instanceof WeatherError)) throw error;
      failure = error;
    }
    for (const snapshot of snapshots) {
      if (snapshot.text === serverText) continue;
      try {
        const candidate = accept(snapshot.text, false);
        if (!accepted) { result = candidate; accepted = true; }
        if (snapshot.url.href === url.href) retained = snapshot;
      } catch (error) {
        if (!(error instanceof WeatherError)) throw error;
        failure ??= error;
        await this.remove(snapshot.url);
      }
    }
    if (!accepted) throw failure;
    if (serverBytes) {
      if (retained) await this.store(previousUrl, retained.bytes, retained.cachedAt);
      await this.store(url, serverBytes);
    }
    return result as T;
  }

  async prepared(asset: PreparedAsset, accept: (bytes: Uint8Array) => void): Promise<void> {
    if (!/^[a-f0-9]{64}$/.test(asset.sha256) || asset.file !== `${asset.sha256}.npz`
      || !Number.isSafeInteger(asset.bytes) || asset.bytes <= 0 || asset.bytes > MAX_PAYLOAD) {
      throw new WeatherError("WEATHER_CATALOG_INVALID", "予報配信file情報が不正です。");
    }
    const url = new URL(asset.file, this.base);
    const validate = (bytes: Uint8Array) => {
      if (bytes.byteLength !== asset.bytes) throw new WeatherError(
        "WEATHER_PAYLOAD_INTEGRITY_FAILED", "予報データの長さが配信情報と一致しません。");
      accept(bytes); // The upstream portable codec validates SHA-256, format and budgets.
    };
    const cached = await this.cached(url, PAYLOAD_TTL);
    let corrupt = false;
    if (cached) {
      try { validate(await this.read(cached, MAX_PAYLOAD)); return; }
      catch (error) {
        // A valid snapshot can lack the requested time without being corrupt.
        // Keep it for covered requests; downloading the same hash cannot add data.
        if (error instanceof WeatherError && error.code === "WEATHER_PREPARED_UNAVAILABLE") throw error;
        corrupt = true; await this.remove(url);
      }
    }
    let bytes: Uint8Array;
    try { bytes = await this.download(url, MAX_PAYLOAD, false); }
    catch (error) {
      if (corrupt) throw new WeatherError("WEATHER_CACHE_CORRUPT",
        `予報 cacheが破損し、再取得できません。${error instanceof Error ? error.message : ""}`);
      throw error;
    }
    validate(bytes);
    await this.store(url, bytes);
  }
}
