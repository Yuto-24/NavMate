"""Private, bounded transport for the one reviewed #431 preparation.

No provider calls. Original evidence and plan bytes are never rewritten. The
encrypted result excludes candidate checkouts, caches and complete logs. Only
bounded failure details may be retained inside the encrypted private journal.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import zipfile
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

CURRENT = "03cc463cf09192e1403f839df4165410c5db8d7b"
CANDIDATE = "f1a5ef49eeab41744635232cddd51c2257871aed"
TOOLING = "64225b82c9b2e978409f0b35490be3c83af3f157"
RECORD_SHA256 = "c8db8b709497e4071d937fba768c89e48c0d7712f0a4a87bfe88f661d72889ba"
EVIDENCE_ROOT = Path("/home/yuto/autonavlog-releases/schema4-5-v2.3.2-20261113")
RECORD_NAME = "SCHEMA_RECORD.json"
ROLES = ("old_to_new", "old_writer_coexistence", "storage_sync_roundtrip")
MAX_SECRET = 48_000  # Below GitHub's 48 KiB per-secret limit, including encoding.
MAX_ENVELOPE = 36 * 1024 * 1024
MAX_RECORD = 1024 * 1024
MAX_REPORT = 8 * 1024 * 1024
MAX_PAYLOAD = 480 * 1024 * 1024
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_FILES = 25_000
MAGIC = b"NavMate-schema431-AES256GCM-v1\0"


class InvalidBundle(Exception):
    """Only fixed diagnostic codes may leave this module."""


def require(condition: object, code: str) -> None:
    if not condition:
        raise InvalidBundle(code)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_file(path: Path, limit: int, *, private: bool = False,
              allow_empty: bool = False) -> bytes:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and (allow_empty or info.st_size > 0)
            and info.st_size <= limit, "file-type-or-size")
    if private:
        require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, "file-permissions")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) == info.st_size, "file-changed-or-too-large")
    return raw


def write_private(path: Path, raw: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(raw)


def key_bytes(encoded: str) -> bytes:
    raw = base64.b64decode(encoded.strip(), validate=True)
    require(len(raw) == 32, "archive-key")
    return raw


def report_names(record: dict) -> dict[str, str]:
    """Only files inside the already reviewed evidence directory are transferable."""
    result = {}
    for role in ROLES:
        value = record["checks"][role]["record"]["path"]
        require(isinstance(value, str) and "\\" not in value, "evidence-path")
        path = PurePosixPath(value)
        require(".." not in path.parts and str(path) == value, "evidence-path")
        if path.is_absolute():
            path = path.relative_to(EVIDENCE_ROOT.as_posix())
        require(path.parts and path.suffix == ".json" and not path.is_absolute()
                and all(part not in ("", ".", "..") for part in path.parts), "evidence-path")
        name = str(path)
        require(name != RECORD_NAME and name not in result.values(), "duplicate-evidence-path")
        result[role] = name
    return result


def evidence_files(raw: bytes, reports: dict[str, bytes]) -> dict[str, bytes]:
    require(0 < len(raw) <= MAX_RECORD and sha256(raw) == RECORD_SHA256, "record-hash")
    record = json.loads(raw)
    require(record.get("sha") == CANDIDATE and record.get("current_sha") == CURRENT
            and record.get("tooling_sha") == TOOLING
            and record.get("kind") == "forecast-model-selection", "record-identity")
    require(set(reports) == set(ROLES), "report-set")
    names = report_names(record)
    files = {RECORD_NAME: raw}
    identity = {key: value for key, value in record.items() if key != "checks"}
    for role, name in names.items():
        content, check = reports[role], record["checks"][role]
        require(0 < len(content) <= MAX_REPORT
                and sha256(content) == check["record"]["sha256"], "report-hash")
        report = json.loads(content)
        require(report.get("identity") == identity and report.get("check") == role
                and check.get("result") == "PASS"
                and all(isinstance(check.get(key), str) and check[key].strip()
                        for key in ("reviewed_by", "summary"))
                and all(report.get(key) == check[key]
                        for key in ("result", "reviewed_by", "summary")), "report-identity")
        files[name] = content
    return files


def pack(record_path: Path, destination: Path) -> None:
    raw = read_file(record_path, MAX_RECORD, private=True)
    record = json.loads(raw)
    names = report_names(record)
    reports = {
        role: read_file(record_path.parent / record["checks"][role]["record"]["path"],
                        MAX_REPORT, private=True)
        for role in names
    }
    evidence_files(raw, reports)
    key = os.urandom(32)
    now = datetime.now(UTC)
    envelope = {
        "schema_version": 1,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "archive_key_sha256": sha256(key),
        "record": base64.b64encode(raw).decode("ascii"),
        "reports": {role: base64.b64encode(content).decode("ascii")
                    for role, content in reports.items()},
    }
    serialized = json.dumps(envelope, separators=(",", ":")).encode()
    require(len(serialized) <= MAX_ENVELOPE, "envelope-size")
    compressor = zlib.compressobj(level=9, wbits=31)
    secret = base64.b64encode(compressor.compress(serialized) + compressor.flush())
    require(len(secret) <= MAX_SECRET, "secret-size")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    write_private(destination / "evidence.secret", secret)
    write_private(destination / "archive.key", base64.b64encode(key))


def open_secret(encoded: str, key: bytes, now: datetime) -> dict[str, bytes]:
    require(0 < len(encoded) <= MAX_SECRET, "secret-size")
    compressed = base64.b64decode(encoded, validate=True)
    inflater = zlib.decompressobj(wbits=31)
    raw = inflater.decompress(compressed, MAX_ENVELOPE + 1)
    require(len(raw) <= MAX_ENVELOPE and inflater.eof and not inflater.unused_data
            and not inflater.unconsumed_tail, "envelope-size-or-format")
    envelope = json.loads(raw)
    created = datetime.fromisoformat(envelope["created_at"])
    expires = datetime.fromisoformat(envelope["expires_at"])
    require(envelope.get("schema_version") == 1 and created.tzinfo is not None
            and expires.tzinfo is not None and created <= now < expires
            and expires - created == timedelta(hours=24), "transport-expired")
    require(envelope.get("archive_key_sha256") == sha256(key), "archive-key-mismatch")
    return evidence_files(
        base64.b64decode(envelope["record"], validate=True),
        {role: base64.b64decode(value, validate=True)
         for role, value in envelope["reports"].items()},
    )


def restore_evidence(files: dict[str, bytes], *, existing: bool = False) -> None:
    """Preserve absolute receipt paths; never overwrite the WSL originals."""
    for ancestor in (EVIDENCE_ROOT, *EVIDENCE_ROOT.parents):
        require(not ancestor.is_symlink(), "evidence-symlink")
    if EVIDENCE_ROOT.exists():
        require(existing, "evidence-already-exists")
        info = EVIDENCE_ROOT.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_mode & 0o077 == 0
                and info.st_uid == os.getuid(), "evidence-permissions")
        for name, raw in files.items():
            path = EVIDENCE_ROOT / name
            require(path.resolve() == path and read_file(path, MAX_REPORT, private=True) == raw,
                    "existing-evidence-conflict")
        return
    EVIDENCE_ROOT.mkdir(mode=0o700)
    try:
        for name, raw in files.items():
            write_private(EVIDENCE_ROOT / name, raw)
    except Exception:
        shutil.rmtree(EVIDENCE_ROOT)
        raise


def archive_files(store: Path, evidence: dict[str, bytes], success: bool,
                  *, publication: bool = False):
    for name, raw in evidence.items():
        yield "evidence/" + name, raw
    for name in ("prepare-status.json", "handoff.json"):
        yield "store/" + name, read_file(store / name, MAX_RECORD)
    if publication:
        yield "store/publish-status.json", read_file(store / "publish-status.json", MAX_RECORD)
    if success:
        for name in ("plan.json", "prepared/feed-report.json"):
            yield "store/" + name, read_file(store / name, MAX_REPORT)
        upload = store / "prepared/upload"
        require(upload.is_dir() and not upload.is_symlink(), "upload-directory")
        for path in sorted(upload.rglob("*")):
            require(not path.is_symlink(), "upload-symlink")
            if path.is_dir():
                continue
            yield "store/prepared/upload/" + path.relative_to(upload).as_posix(), read_file(
                path, MAX_PAYLOAD, allow_empty=True)


def seal(store: Path, evidence: dict[str, bytes], key: bytes, output: Path,
         *, success: bool, publication: bool = False) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    buffer = io.BytesIO()
    total, count = 0, 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in archive_files(store, evidence, success, publication=publication):
            total += len(raw)
            count += 1
            require(total <= MAX_PAYLOAD and count <= MAX_FILES, "archive-capacity")
            archive.writestr(name, raw)
    require(buffer.tell() + len(MAGIC) + 28 <= MAX_ARCHIVE, "archive-capacity")
    nonce = os.urandom(12)
    encrypted = MAGIC + nonce + AESGCM(key).encrypt(nonce, buffer.getvalue(), MAGIC)
    # A failed write must not leave a partial final archive that blocks recovery.
    # Hard-linking the completed file is atomic and cannot overwrite an existing
    # result; both paths are on the same filesystem.
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encrypted)
        os.link(temporary, output)
    finally:
        with contextlib.suppress(OSError):
            Path(temporary).unlink()
    return sha256(encrypted)


def unseal(archive_path: Path, key_path: Path, destination: Path) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = key_bytes(read_file(key_path, 256, private=True).decode("ascii"))
    raw = read_file(archive_path, MAX_ARCHIVE)
    require(raw.startswith(MAGIC) and len(raw) > len(MAGIC) + 28, "archive-format")
    start = len(MAGIC)
    payload = AESGCM(key).decrypt(raw[start:start + 12], raw[start + 12:], MAGIC)
    files, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        require(0 < len(archive.infolist()) <= MAX_FILES, "archive-capacity")
        for member in archive.infolist():
            name = member.filename
            path = PurePosixPath(name)
            total += member.file_size
            require(not member.is_dir() and not path.is_absolute() and ".." not in path.parts
                    and str(path) == name and "\\" not in name and name not in files
                    and total <= MAX_PAYLOAD, "archive-path-or-capacity")
            require(name.startswith("evidence/") or name in (
                "store/plan.json", "store/prepare-status.json", "store/publish-status.json",
                "store/handoff.json",
                "store/prepared/feed-report.json")
                or name.startswith("store/prepared/upload/"), "archive-file")
            files[name] = archive.read(member)
    record = files["evidence/" + RECORD_NAME]
    names = report_names(json.loads(record))
    evidence = evidence_files(record, {role: files["evidence/" + name]
                                       for role, name in names.items()})
    require({name for name in files if name.startswith("evidence/")}
            == {"evidence/" + name for name in evidence}, "archive-evidence-set")
    handoff = json.loads(files["store/handoff.json"])
    require(handoff.get("tooling_sha") == TOOLING and handoff.get("sha") == CANDIDATE
            and handoff.get("current_sha") == CURRENT, "handoff-identity")
    plan_raw = files.get("store/plan.json")
    if handoff["prepared"]:
        require(plan_raw is not None and sha256(plan_raw) == handoff["plan_sha256"], "plan-hash")
        plan = json.loads(plan_raw)
        require(plan["sha"] == CANDIDATE and plan["current_sha"] == CURRENT
                and plan["snapshot"]["tooling_sha"] == TOOLING
                and plan["snapshot"]["schema_receipt"]["path"]
                == str(EVIDENCE_ROOT / RECORD_NAME), "plan-identity-or-path")
    require(not destination.exists() and not destination.is_symlink(), "store-already-exists")
    restore_evidence(evidence, existing=True)
    destination.mkdir(mode=0o700)
    for name, content in files.items():
        if name.startswith("store/"):
            write_private(destination / name.removeprefix("store/"), content)
    if handoff["prepared"]:
        created = datetime.fromisoformat(plan["prepared_at"])
        handoff["within_plan_window"] = (
            datetime.now(UTC) - timedelta(minutes=30) <= created <= datetime.now(UTC))
    return handoff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    packing = sub.add_parser("pack")
    packing.add_argument("--schema-record", type=Path, required=True)
    packing.add_argument("--output", type=Path, required=True)
    opening = sub.add_parser("unpack")
    opening.add_argument("--archive", type=Path, required=True)
    opening.add_argument("--key", type=Path, required=True)
    opening.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.mode == "pack":
        pack(args.schema_record, args.output)
        print(json.dumps({"status": "PACKED", "transport_valid_hours": 24}))
    else:
        result = unseal(args.archive, args.key, args.store)
        print(json.dumps({"status": "RESTORED", "prepared": result["prepared"],
                          "plan_sha256": result.get("plan_sha256"),
                          "within_plan_window": result.get("within_plan_window", False)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Native parse/crypto/path errors may contain private bytes or paths.
        sys.exit('Schema431 bundle BLOCKED; inspect private inputs without printing them')
