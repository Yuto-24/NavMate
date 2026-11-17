// Wire contract shared with autonavlog.web.sync_payload. Local records remain JSON.
export const SYNC_PAYLOAD_PREFIX = "gzip-v1:";
export const COMPRESSION_THRESHOLD = 256 * 1024;
export const MAX_STORED_BYTES = 1_000_000;
export const MAX_DECODED_BYTES = 16 * 1024 * 1024;
const utf8 = new TextEncoder();
const invalid = () => Object.assign(new Error("Invalid or oversized Account Sync payload"), { code: "invalid-argument" });

function base64(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(binary);
}

async function collect(stream: ReadableStream<Uint8Array>, limit: number): Promise<Uint8Array<ArrayBuffer>> {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw invalid();
      chunks.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return bytes;
}

export async function encodeSyncPayload(payload: string): Promise<string> {
  const raw = utf8.encode(payload);
  if (raw.byteLength > MAX_DECODED_BYTES) throw invalid();
  let result = payload;
  if (raw.byteLength >= COMPRESSION_THRESHOLD) {
    const packed = await collect(new Blob([raw]).stream().pipeThrough(new CompressionStream("gzip")), MAX_DECODED_BYTES + 65536);
    const encoded = SYNC_PAYLOAD_PREFIX + base64(packed);
    if (encoded.length < raw.byteLength) result = encoded;
  }
  if (utf8.encode(result).byteLength > MAX_STORED_BYTES) throw invalid();
  return result;
}

export async function decodeSyncPayload(payload: string): Promise<string> {
  if (!payload.startsWith(SYNC_PAYLOAD_PREFIX)) {
    // Do not reject valid historical documents above the new write budget.
    if (utf8.encode(payload).byteLength > MAX_DECODED_BYTES) throw invalid();
    return payload;
  }
  if (payload.length > MAX_STORED_BYTES) throw invalid();
  const encoded = payload.slice(SYNC_PAYLOAD_PREFIX.length);
  const binary = atob(encoded);
  if (btoa(binary) !== encoded) throw invalid();
  const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
  const raw = await collect(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip")), MAX_DECODED_BYTES);
  return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(raw);
}
