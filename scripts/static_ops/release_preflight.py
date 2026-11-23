"""Read-only release routing against the actual approved production application.

A recognized migration is a request for evidence, never publication approval.
Candidate source is read as data; only trusted main tooling is executed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.static_ops import app_release as app  # noqa: E402

KINDS = (
    "reference-snapshot-writer-fence",
    "forecast-model-selection",
    "aip-reference-source-writer-fence",
)
SCHEMA = "data/schemas/project.schema.json"
WRITER = "web/src/localProjectRepository.ts"


def database_version(operator, sha: str) -> int:
    source = operator.git("show", f"{sha}:{WRITER}")
    matches = re.findall(r"export const LOCAL_DATABASE_VERSION = ([1-9][0-9]*);", source)
    if len(matches) == 1 and ", LOCAL_DATABASE_VERSION)" in source:
        return int(matches[0])
    app.require(not matches and ", 1)" in source, "Unknown database writer contract")
    return 1


def classify(operator, sha: str, current: str) -> dict:
    changed = [
        path
        for path in app.COMPATIBILITY
        if operator.source_digest(sha, path) != operator.source_digest(current, path)
    ]
    result = {
        "route": "BLOCKED",
        "kind": None,
        "changed_contracts": changed,
        "publication_authorized": False,
    }
    if any(path != SCHEMA for path in changed):
        return {**result, "reason": "Rules or index changes require individual migration review"}
    if not changed:
        if database_version(operator, sha) != database_version(operator, current):
            return {
                **result,
                "reason": "Database version changed outside a supported schema migration",
            }
        return {
            **result,
            "route": "AUTOMATIC",
            "reason": "Existing access and data contracts unchanged",
        }
    matches = []
    for kind in KINDS:
        try:
            operator.schema_shape(sha, current, kind)
        except app.Blocked:
            continue
        matches.append(kind)
    if len(matches) != 1:
        return {**result, "reason": "Unknown or ambiguous schema migration"}
    kind = matches[0]
    if kind != KINDS[2]:
        return {
            **result,
            "kind": kind,
            "reason": "Known legacy contract has no automated evidence recipe; individual migration required",  # noqa: E501
            "next_step": "Use the separately reviewed legacy migration procedure",
        }
    return {
        **result,
        "route": "MANUAL",
        "kind": kind,
        "next_step": "Review the private evidence, dispatch prepare-migration, then approve publish-migration",  # noqa: E501
        "reason": (
            "Recognized contract; pinned compatibility evidence and explicit approval required"
        ),
        "required_checks": [
            "old_to_new",
            "old_writer_coexistence" if kind == KINDS[1] else "old_writer_fenced",
            "storage_sync_roundtrip",
        ],
    }


def inspect(operator, sha: str, current: str) -> dict:
    app.require(re.fullmatch(r"[0-9a-f]{40}", sha), "Full candidate commit required")
    app.require(re.fullmatch(r"[0-9a-f]{40}", current), "Full approved commit required")
    canonical = app.release(app.gate.ORIGIN, current)
    app.require(
        canonical.get("commit") == current
        and canonical.get("dirty") is False
        and isinstance(canonical.get("configuration"), dict),
        "Canonical, approved source or public configuration mismatch",
    )
    for commit in (current, sha):
        operator.git("fetch", "origin", commit)
        app.require(
            operator.git("rev-parse", commit + "^{commit}") == commit, "Source identity mismatch"
        )
    result = classify(operator, sha, current)
    again = app.release(app.gate.ORIGIN, current)
    app.require(
        all(again.get(key) == canonical.get(key) for key in ("commit", "dirty", "configuration")),
        "Production changed during preflight",
    )
    return {
        **result,
        "candidate_sha": sha,
        "current_sha": current,
        "tooling_sha": operator.git("rev-parse", "HEAD"),
        "configuration_digest": app.fingerprint(canonical["configuration"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    try:
        result = inspect(app.Operator(), args.sha, os.environ.get("STATIC_APPROVED_SHA", ""))
    except Exception:
        # Provider details and full configuration inventories are private.
        result = {
            "route": "BLOCKED",
            "publication_authorized": False,
            "reason": "Preflight unavailable; reconcile production and access before retry",
        }
    raw = json.dumps(result, sort_keys=True)
    print(raw)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
            output.write("## Release route\n\n```json\n" + raw + "\n```\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write("route=" + result["route"] + "\n")
    return 1 if result["route"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
