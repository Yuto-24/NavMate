"""Lossless Firestore payload encoding, shared with web/src/syncPayload.ts.

The outer #185 envelope and LocalProjectRecord stay unchanged. Old clients reject
our non-JSON prefix before writing; receipts compare the decoded durable content.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import zlib

PREFIX = "gzip-v1:"
COMPRESSION_THRESHOLD = 256 * 1024
# Leave room for the envelope and document name under Firestore's 1 MiB limit.
MAX_STORED_BYTES = 1_000_000
MAX_DECODED_BYTES = 16 * 1024 * 1024


def encode_payload(payload: str) -> str:
    raw = payload.encode("utf-8")
    if len(raw) > MAX_DECODED_BYTES:
        raise ValueError("Account Sync payload exceeds decoded size limit")
    result = payload
    if len(raw) >= COMPRESSION_THRESHOLD:
        packed = PREFIX + base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")
        if len(packed) < len(raw):
            result = packed
    if len(result.encode("utf-8")) > MAX_STORED_BYTES:
        raise ValueError("Account Sync payload exceeds stored size limit")
    return result


def decode_payload(payload: str) -> str:
    if not payload.startswith(PREFIX):
        # Existing uncompressed documents may exceed our new write budget.
        if len(payload.encode("utf-8")) > MAX_DECODED_BYTES:
            raise ValueError("Account Sync payload exceeds decoded size limit")
        return payload
    if len(payload) > MAX_STORED_BYTES:
        raise ValueError("Account Sync payload exceeds stored size limit")
    try:
        encoded = payload[len(PREFIX) :]
        packed = base64.b64decode(encoded, validate=True)
        if base64.b64encode(packed).decode("ascii") != encoded:
            raise ValueError("Noncanonical Account Sync base64")
        decoder = zlib.decompressobj(wbits=31)
        raw = decoder.decompress(packed, MAX_DECODED_BYTES + 1)
        if (
            len(raw) > MAX_DECODED_BYTES
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            raise ValueError("Invalid or oversized Account Sync gzip")
        return raw.decode("utf-8")
    except (binascii.Error, zlib.error, UnicodeError) as error:
        raise ValueError("Invalid Account Sync payload encoding") from error
