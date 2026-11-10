"""GET-only production identity check for the v2.3.1 schema transition (#423).

This is an observation, not a release plan, compatibility attestation, or
authorization to run prepare/publish. Never return provider responses or tokens.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.static_ops import app_release as app  # noqa: E402
from scripts.static_ops import publication_gate as gate  # noqa: E402

CURRENT = "03cc463cf09192e1403f839df4165410c5db8d7b"
CANDIDATE = "c717ac6baaa3d7556120d2a7f6c9435f165f132b"
PROJECT = "navmate-prod"
RULES_PATH = "firebase/firestore.rules"


class ReadbackBlocked(Exception):
    """Only a fixed, non-secret phase name may leave this process."""


def step(phase: str, action):
    try:
        return action()
    except Exception:
        raise ReadbackBlocked(phase) from None


def observe(operator: app.Operator, env: dict[str, str], *, canonical_reader=app.release) -> dict:
    """Read the canonical app, full Pages inventory, and live Rules; never mutate."""
    if (
        env.get("STATIC_APPROVED_SHA") != CURRENT
        or env.get("VITE_FIREBASE_PROJECT_ID") != PROJECT
        or not re.fullmatch(r"[0-9a-f]{32}", env.get("CLOUDFLARE_ACCOUNT_ID", ""))
    ):
        raise ReadbackBlocked("scope")
    if not env.get("CLOUDFLARE_API_TOKEN") or not env.get("STATIC_GOOGLE_ACCESS_TOKEN"):
        raise ReadbackBlocked("credentials")

    def source_identity() -> str:
        if operator.git("rev-parse", "v2.3.1^{commit}") != CANDIDATE:
            raise ValueError("release tag mismatch")
        operator.git("merge-base", "--is-ancestor", CANDIDATE, "HEAD")
        before = operator.source_digest(CURRENT, RULES_PATH)
        after = operator.source_digest(CANDIDATE, RULES_PATH)
        if before != after:
            raise ValueError("Rules source differs")
        index_path = "firebase/firestore.indexes.json"
        if operator.source_digest(CURRENT, index_path) != operator.source_digest(
            CANDIDATE, index_path
        ):
            raise ValueError("Indexes source differs")
        return app.digest(operator.rules_source(CANDIDATE).encode("utf-8"))

    rules_digest = step("source", source_identity)
    canonical = step("canonical", lambda: canonical_reader(gate.ORIGIN, CURRENT))
    if canonical.get("version") != "2.2.2":
        raise ReadbackBlocked("canonical_identity")

    target = step("pages", lambda: operator.target({
        "CLOUDFLARE_ACCOUNT_ID": env["CLOUDFLARE_ACCOUNT_ID"]
    }))
    if target.get("commit") != CURRENT:
        raise ReadbackBlocked("pages_identity")

    def read_live_rules() -> None:
        prefix = f"projects/{PROJECT}"
        release_path = prefix + "/releases/cloud.firestore"
        release = operator.rules_get(release_path)
        ruleset_name = release.get("rulesetName")
        if not isinstance(ruleset_name, str) or not re.fullmatch(
            re.escape(prefix) + r"/rulesets/[A-Za-z0-9-]{1,128}", ruleset_name
        ):
            raise ValueError("Ruleset scope mismatch")
        ruleset = operator.rules_get(ruleset_name)
        files = ruleset.get("source", {}).get("files")
        if (
            not isinstance(files, list)
            or len(files) != 1
            or not isinstance(files[0], dict)
            or files[0].get("name") != RULES_PATH
            or not isinstance(files[0].get("content"), str)
            or app.digest(files[0]["content"].encode("utf-8")) != rules_digest
        ):
            raise ValueError("Live Rules differ")
        if operator.rules_get(release_path) != release:
            raise ValueError("Rules changed during observation")

    step("live_rules", read_live_rules)
    return {
        "status": "MATCH",
        "purpose": "read_only_schema_423_observation_not_publication_approval",
        "current_sha": CURRENT,
        "candidate_sha": CANDIDATE,
        "pages_deployment_id": target["id"],
        "pages_project_digest": target["project_digest"],
        "live_rules_source_sha256": rules_digest,
        "observations": [
            "canonical_release_identity",
            "pages_full_inventory_and_production_identity",
            "live_rules_exact_source_and_stability",
        ],
    }


def main() -> int:
    try:
        result = observe(app.Operator(), dict(os.environ))
    except ReadbackBlocked as error:
        result = {"status": "BLOCKED", "phase": str(error)}
    except Exception:
        result = {"status": "BLOCKED", "phase": "unexpected_failure"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
