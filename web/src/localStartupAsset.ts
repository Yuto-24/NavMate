// Content-Length can describe compressed bytes while fetch exposes decoded
// chunks. Only use a comparable, known byte count for download progress.
export async function readStartupAsset(response: Response, received: (fraction: number) => void): Promise<Uint8Array> {
  const size = Number(response.headers.get("content-length"));
  if (!response.body || !Number.isFinite(size) || size <= 0 || response.headers.has("content-encoding")) {
    return new Uint8Array(await response.arrayBuffer());
  }
  let bytes = 0;
  const stream = response.body.pipeThrough(new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      bytes += chunk.byteLength;
      received(Math.min(bytes / size, 1));
      controller.enqueue(chunk);
    },
  }));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
