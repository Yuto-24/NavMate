"""Small allowlisted release observations; never publication authorization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

if __package__:
    from . import release_timing as timing
else:
    import release_timing as timing

MAX_BYTES = 64 * 1024
CATALOG = "weather/msm/catalog.json"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timezone required")
    return parsed.astimezone(UTC)


def windows(prepared_at: str, generated_at: str, now: datetime) -> dict:
    """Same inclusive 30-minute boundary as the existing gates; advisory only."""
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    prepared, generated = instant(prepared_at), instant(generated_at)
    plan_end, feed_end = prepared + timedelta(minutes=30), generated + timedelta(minutes=30)
    return {
        "plan_deadline": plan_end.isoformat(),
        "feed_deadline": feed_end.isoformat(),
        "earliest_deadline": min(plan_end, feed_end).isoformat(),
        "observed_at": now.astimezone(UTC).isoformat(),
        "remaining_seconds": (min(plan_end, feed_end) - now).total_seconds(),
        "plan_within_window": prepared <= now <= plan_end,
        "feed_within_window": generated <= now <= feed_end,
        "sufficient_for_publication": False,
    }


def identity(env: dict) -> dict:
    run, attempt = env.get("GITHUB_RUN_ID"), env.get("GITHUB_RUN_ATTEMPT")
    if run is None and attempt is None:
        return {"run_id": None, "run_attempt": None}
    if not all(isinstance(v, str) and re.fullmatch(r"[1-9]\d{0,19}", v) for v in (run, attempt)):
        raise ValueError("Invalid run identity")
    return {"run_id": run, "run_attempt": attempt}


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepared(store: Path) -> dict:
    raw = (store / "plan.json").read_bytes()
    plan = json.loads(raw)
    root = store / "prepared/upload/dist-static"
    release_raw = (root / "release.json").read_bytes()
    catalog_raw = (root / CATALOG).read_bytes()
    report_raw = (store / "prepared/feed-report.json").read_bytes()
    release = json.loads(release_raw)
    catalog = json.loads(catalog_raw)
    if (
        sha256(release_raw) != plan["release_digest"]
        or sha256(report_raw) != plan["feed_report_digest"]
        or release["files"][CATALOG] != {"bytes": len(catalog_raw), "sha256": sha256(catalog_raw)}
    ):
        raise ValueError("Prepared evidence changed")
    hashes = {key: plan[key] for key in ("release_digest", "feed_report_digest")}
    hashes.update(plan_sha256=sha256(raw), catalog_sha256=sha256(catalog_raw))
    for value in hashes.values():
        if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
            raise ValueError("Invalid digest")
    return {
        **hashes,
        "prepared_at": instant(plan["prepared_at"]).isoformat(),
        "generated_at": instant(catalog["generated_at"]).isoformat(),
    }


def create(
    store: Path, journal: dict, *, env: dict | None = None, archive: Path | None = None
) -> dict:
    """No private object is copied: construct fields explicitly, fail closed."""
    mode = journal.get("mode")
    if mode not in ("prepare", "publish"):
        raise ValueError("Invalid mode")
    status = journal.get("status")
    if status not in ("OK", "PUBLISHED", "BLOCKED", "RUNNING"):
        raise ValueError("Invalid status")
    phase = journal.get("stage")
    if phase not in timing.PHASES:
        raise ValueError("Invalid stage")
    source = identity(os.environ if env is None else env)
    authorization = journal.get("authorization")
    if mode == "publish" and isinstance(authorization, dict):
        source = identity(
            {
                "GITHUB_RUN_ID": authorization.get("prepare_run_id"),
                "GITHUB_RUN_ATTEMPT": authorization.get("prepare_run_attempt"),
            }
        )
    elif mode == "publish":
        source = {"run_id": None, "run_attempt": None}
        if (store / "plan.json").is_file():
            try:
                origin = json.loads((store / "plan.json").read_text()).get("origin", {})
                source = identity(
                    {
                        "GITHUB_RUN_ID": origin.get("run_id"),
                        "GITHUB_RUN_ATTEMPT": origin.get("run_attempt"),
                    }
                )
            except Exception:
                pass  # Original identity is unavailable, not inferred from the publisher.
    value = {
        "schema_version": 1,
        "mode": mode,
        "status": status,
        "stage": phase,
        **identity(os.environ if env is None else env),
        "publication_authorized": False,
        "prepare_run": source,
        "evidence": None,
        "timings": timing.bounded(journal.get("timings", [])),
        "archive_sha256": file_hash(archive) if archive is not None else None,
    }
    try:
        value["evidence"] = prepared(store)
        value["windows"] = windows(
            value["evidence"]["prepared_at"], value["evidence"]["generated_at"], datetime.now(UTC)
        )
        value["evidence_status"] = "AVAILABLE"
    except Exception:
        # Corrupt/missing evidence still gets a useful diagnostic, without raw errors.
        value["evidence"] = None
        value.pop("windows", None)
        value["status"] = "BLOCKED"
        value["evidence_status"] = "UNAVAILABLE"

    return value


def save(path: Path, value: dict) -> str:
    raw = json.dumps(value, sort_keys=True).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("Review capacity exceeded")
    timing.write(path, value)
    return file_hash(path)


def load(
    path: Path,
    expected: str,
    run_id: str | None,
    attempt: str | None,
    *,
    store: Path | None = None,
    archive: Path | None = None,
) -> dict:
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Invalid review file")
    raw = path.read_bytes()
    if not re.fullmatch("[0-9a-f]{64}", expected) or sha256(raw) != expected:
        raise ValueError("Review digest mismatch")
    value = json.loads(raw)
    if (
        value.get("schema_version") != 1
        or value.get("run_id") != run_id
        or value.get("run_attempt") != attempt
        or value.get("publication_authorized") is not False
    ):
        raise ValueError("Review identity mismatch")
    allowed = {
        "schema_version",
        "mode",
        "status",
        "stage",
        "run_id",
        "run_attempt",
        "publication_authorized",
        "prepare_run",
        "evidence",
        "evidence_status",
        "timings",
        "archive_sha256",
    }
    if value.get("evidence") is not None:
        allowed.add("windows")
    if (
        set(value) != allowed
        or type(value["schema_version"]) is not int
        or value["mode"] not in {"prepare", "publish"}
        or value["status"] not in {"OK", "PUBLISHED", "BLOCKED", "RUNNING"}
        or value["stage"] not in timing.PHASES
    ):
        raise ValueError("Invalid review fields")
    source = value["prepare_run"]
    if source != identity(
        {"GITHUB_RUN_ID": source["run_id"], "GITHUB_RUN_ATTEMPT": source["run_attempt"]}
    ):
        raise ValueError("Invalid prepare identity")
    value["timings"] = timing.bounded(value["timings"])
    if value["archive_sha256"] is not None and not re.fullmatch(
        "[0-9a-f]{64}", value["archive_sha256"]
    ):
        raise ValueError("Invalid archive digest")
    if value["evidence"] is not None:
        evidence = value["evidence"]
        hashes = {"plan_sha256", "release_digest", "feed_report_digest", "catalog_sha256"}
        if (
            set(evidence) != hashes | {"prepared_at", "generated_at"}
            or value["evidence_status"] != "AVAILABLE"
            or any(not re.fullmatch("[0-9a-f]{64}", evidence[k]) for k in hashes)
        ):
            raise ValueError("Invalid evidence fields")
    elif value["evidence_status"] != "UNAVAILABLE" or value["status"] != "BLOCKED":
        raise ValueError("Missing evidence")
    if store is not None and value.get("evidence") != prepared(store):
        raise ValueError("Review differs from original evidence")
    if archive is not None and value.get("archive_sha256") != file_hash(archive):
        raise ValueError("Review archive mismatch")
    evidence = value.get("evidence")
    if evidence is not None:
        value["windows"] = windows(
            evidence["prepared_at"], evidence["generated_at"], datetime.now(UTC)
        )
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--attempt")
    parser.add_argument("--store", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    try:
        value = load(
            args.review,
            args.sha256,
            args.run_id,
            args.attempt,
            store=args.store,
            archive=args.archive,
        )
        print(json.dumps(value, sort_keys=True))
    except (Exception, KeyboardInterrupt):
        parser.exit(1, "Release review unavailable or invalid; no authorization\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
