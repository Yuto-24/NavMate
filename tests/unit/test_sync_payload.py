from __future__ import annotations

import base64
import gzip
import json
import random
from pathlib import Path

import pytest

from autonavlog.web.sync_payload import (
    MAX_DECODED_BYTES,
    MAX_STORED_BYTES,
    PREFIX,
    decode_payload,
    encode_payload,
)


def packed(raw: bytes) -> str:
    return PREFIX + base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")


def test_shared_wire_vector_and_existing_uncompressed_documents():
    vector = json.loads(
        (Path(__file__).parents[1] / "fixtures/sync-payload.json").read_text()
    )
    assert decode_payload(vector["encoded"]) == vector["payload"]
    assert encode_payload(vector["payload"]) == vector["payload"]
    # Older clients could write closer to the provider limit than our new budget.
    historical = json.dumps({"value": "x" * (MAX_STORED_BYTES + 1000)})
    assert decode_payload(historical) == historical


def test_large_record_is_lossless_including_unicode_and_numeric_spelling():
    payload = '{"text":"' + "宮崎 🌤️" * 100_000 + '","number":1.2300,"minusZero":-0.0}'
    assert len(payload.encode()) > 1_048_576
    encoded = encode_payload(payload)
    assert encoded.startswith(PREFIX)
    assert len(encoded.encode()) < MAX_STORED_BYTES
    assert decode_payload(encoded).encode() == payload.encode()


def test_incompressible_or_oversized_data_is_rejected_without_truncation():
    noise = base64.b64encode(random.Random(1).randbytes(1_100_000)).decode()
    payload = json.dumps({"noise": noise})
    with pytest.raises(ValueError, match="stored size"):
        encode_payload(payload)
    with pytest.raises(ValueError, match="decoded size"):
        encode_payload("x" * (MAX_DECODED_BYTES + 1))
    with pytest.raises(ValueError):
        decode_payload(packed(b"x" * (MAX_DECODED_BYTES + 1)))


@pytest.mark.parametrize(
    "damage", ["base64", "truncated", "checksum", "trailing", "concatenated", "utf8"]
)
def test_invalid_encoding_is_never_adopted(damage):
    raw = gzip.compress(b'{"id":"test"}', mtime=0)
    if damage == "base64":
        value = PREFIX + "!!!"
    else:
        if damage == "truncated":
            raw = raw[:-3]
        elif damage == "checksum":
            raw = raw[:-8] + bytes([raw[-8] ^ 1]) + raw[-7:]
        elif damage == "trailing":
            raw += b"unexpected"
        elif damage == "concatenated":
            raw += gzip.compress(b"second member")
        else:
            raw = gzip.compress(b"\xff")
        value = PREFIX + base64.b64encode(raw).decode()
    with pytest.raises(ValueError):
        decode_payload(value)
