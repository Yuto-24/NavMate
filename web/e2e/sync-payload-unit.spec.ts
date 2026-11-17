import { expect, test } from "@playwright/test";
import { gzipSync } from "node:zlib";
import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
const vector = JSON.parse(readFileSync(new URL("../../tests/fixtures/sync-payload.json", import.meta.url), "utf8"));
import { decodeSyncPayload, encodeSyncPayload, MAX_DECODED_BYTES, MAX_STORED_BYTES, SYNC_PAYLOAD_PREFIX } from "../src/syncPayload";

const pack = (raw: Uint8Array) => SYNC_PAYLOAD_PREFIX + gzipSync(raw).toString("base64");

test("Python wire vector, old JSON and large Unicode record restore exactly", async () => {
  expect(await decodeSyncPayload(vector.encoded)).toBe(vector.payload);
  expect(await encodeSyncPayload(vector.payload)).toBe(vector.payload);
  const historical = JSON.stringify({ value: "x".repeat(MAX_STORED_BYTES + 1000) });
  expect(await decodeSyncPayload(historical)).toBe(historical);
  const raw = '{"text":"' + "宮崎 🌤️".repeat(100_000) + '","number":1.2300,"minusZero":-0.0}';
  expect(new TextEncoder().encode(raw).length).toBeGreaterThan(1_048_576);
  const encoded = await encodeSyncPayload(raw);
  expect(encoded.startsWith(SYNC_PAYLOAD_PREFIX)).toBe(true);
  expect(encoded.length).toBeLessThan(MAX_STORED_BYTES);
  expect(await decodeSyncPayload(encoded)).toBe(raw);
});

test("oversized and incompressible payloads fail without dropping fields", async () => {
  const raw = JSON.stringify({ noise: randomBytes(1_100_000).toString("base64") });
  await expect(encodeSyncPayload(raw)).rejects.toMatchObject({ code: "invalid-argument" });
  await expect(encodeSyncPayload("x".repeat(MAX_DECODED_BYTES + 1))).rejects.toMatchObject({ code: "invalid-argument" });
  await expect(decodeSyncPayload(pack(Buffer.alloc(MAX_DECODED_BYTES + 1, 120)))).rejects.toBeDefined();
});

test("corrupt gzip, noncanonical base64, invalid UTF-8 and trailing data are rejected", async () => {
  const raw = gzipSync(Buffer.from(vector.payload));
  const checksum = Buffer.from(raw); checksum[checksum.length - 8]! ^= 1;
  const invalid = ["!!!", raw.subarray(0, -3).toString("base64"), checksum.toString("base64"),
    Buffer.concat([raw, Buffer.from("unexpected")]).toString("base64"),
    gzipSync(Buffer.from([255])).toString("base64"), " " + raw.toString("base64")];
  for (const value of invalid) await expect(decodeSyncPayload(SYNC_PAYLOAD_PREFIX + value)).rejects.toBeDefined();
  // Some native gzip implementations accept concatenated members; the JSON boundary
  // must still reject a second record rather than partially accepting the first.
  const concatenated = Buffer.concat([raw, gzipSync(Buffer.from("{}"))]).toString("base64");
  await expect(decodeSyncPayload(SYNC_PAYLOAD_PREFIX + concatenated).then(JSON.parse)).rejects.toBeDefined();
});
