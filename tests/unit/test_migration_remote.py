from __future__ import annotations

import json
from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from autonavlog.web.migration_remote import FirebaseTokenVerifier, decode_fields, encode_fields


@pytest.fixture
def signed(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_key_from_jwt(self, token):
            class Key:
                key = private.public_key()

            return Key()

    now = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": "https://securetoken.google.com/test",
        "aud": "test",
        "sub": "firebase-user",
        "iat": now,
        "exp": now + 60,
        "auth_time": now,
        "firebase": {
            "sign_in_provider": "google.com",
            "identities": {"google.com": ["immutable-subject"]},
        },
    }
    result = {
        "users": [
            {
                "localId": "firebase-user",
                "providerUserInfo": [{"providerId": "google.com", "rawId": "immutable-subject"}],
            }
        ]
    }
    monkeypatch.setattr("autonavlog.web.migration_remote.request_json", lambda *args: result)
    return FirebaseTokenVerifier("test", "public-key", Keys()), private, claims, result


def test_google_id_matches_browser_contract_and_ignores_email(signed):
    import hashlib

    verifier, private, claims, result = signed
    account = verifier.verify(jwt.encode(claims, private, algorithm="RS256"))
    expected = hashlib.sha256(
        b'["autonavlog.account.v1","https://accounts.google.com","immutable-subject"]'
    ).hexdigest()
    assert account.account_id == "account_v1_" + expected
    claims["email"] = "someone-else@example.com"
    assert verifier.verify(jwt.encode(claims, private, algorithm="RS256")) == account


@pytest.mark.parametrize(
    "damage",
    ["aud", "iss", "expired", "provider", "subjects", "disabled", "revoked", "lookup-subject"],
)
def test_invalid_google_credentials_are_rejected(signed, damage):
    verifier, private, claims, result = signed
    if damage in {"aud", "iss"}:
        claims[damage] = "wrong"
    elif damage == "expired":
        claims["exp"] = 1
    elif damage == "provider":
        claims["firebase"]["sign_in_provider"] = "password"
    elif damage == "subjects":
        claims["firebase"]["identities"]["google.com"].append("other")
    elif damage == "disabled":
        result["users"][0]["disabled"] = True
    elif damage == "revoked":
        result["users"][0]["validSince"] = str(claims["auth_time"] + 1)
    else:
        result["users"][0]["providerUserInfo"][0]["rawId"] = "other"
    with pytest.raises((ValueError, jwt.PyJWTError)):
        verifier.verify(jwt.encode(claims, private, algorithm="RS256"))


def test_firestore_envelope_roundtrip():
    value = {
        "schema": 1,
        "id": "id",
        "payload": '{"nested":[[1,2]]}',
        "latestDeviceId": None,
        "revision": 3,
        "undoUntil": None,
        "deletion": "ACTIVE",
        "version": "version",
    }
    assert decode_fields(encode_fields(value)) == value


def test_rest_adapter_compresses_writes_and_decodes_reads_without_mutating_receipts(monkeypatch):
    from autonavlog.web.migration_remote import FirestoreMigrationRemote, GoogleIdentity
    from autonavlog.web.sync_payload import PREFIX, decode_payload

    payload = json.dumps({"id": "synthetic", "calculation": "full result " * 110_000})
    intended = {
        "schema": 1, "id": "synthetic", "payload": payload, "revision": 1,
        "version": "operation-1", "baseVersion": None, "deletion": "ACTIVE",
        "undoUntil": None, "latestDeviceId": None,
    }
    stored = {}
    calls = []

    def request(url, body, token):
        assert token == "synthetic-token"
        calls.append(url)
        if url.endswith(":commit"):
            write, = body["writes"]
            assert write["currentDocument"] == {"exists": False}
            stored.update(write["update"])
            return {}
        assert url.endswith(":batchGet")
        return [{"found": {**stored, "updateTime": "server-version"}}]

    monkeypatch.setattr("autonavlog.web.migration_remote.request_json", request)
    remote = FirestoreMigrationRemote(
        "test", GoogleIdentity("subject", "account"), "synthetic-token"
    )
    remote.commit([(intended, None)])
    wire = decode_fields(stored["fields"])
    assert wire["payload"].startswith(PREFIX)
    assert decode_payload(wire["payload"]) == payload
    assert intended["payload"] == payload  # Durable receipts keep their existing representation.
    assert remote.read(["synthetic"])["synthetic"] == {**intended, "_updateTime": "server-version"}
    assert len(calls) == 2


def test_oversized_commit_is_rejected_before_any_network_write(monkeypatch):
    from autonavlog.web.migration_remote import FirestoreMigrationRemote, GoogleIdentity
    from autonavlog.web.sync_payload import MAX_DECODED_BYTES

    calls = []
    monkeypatch.setattr(
        "autonavlog.web.migration_remote.request_json", lambda *args: calls.append(args)
    )
    remote = FirestoreMigrationRemote("test", GoogleIdentity("subject", "account"), "synthetic")
    with pytest.raises(ValueError):
        remote.commit([({"id": "small", "payload": "{}"}, None),
                       ({"id": "large", "payload": "x" * (MAX_DECODED_BYTES + 1)}, None)])
    assert not calls
