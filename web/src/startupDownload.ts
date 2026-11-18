// Content-Length describes compressed bytes when Content-Encoding is present,
// whereas fetch exposes decoded bytes. Only compare like-for-like quantities.
export async function readStartupBytes(response: Response, report: (fraction: number) => void): Promise<Uint8Array> {
  const length = Number(response.headers.get("content-length"));
  const encoding = response.headers.get("content-encoding");
  if (!response.body || !Number.isFinite(length) || length <= 0 || (encoding && encoding !== "identity")) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    report(1);
    return bytes;
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.byteLength;
      report(Math.min(received / length, 1));
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  report(1);
  return bytes;
}
