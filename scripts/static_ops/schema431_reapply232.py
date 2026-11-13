"""Reapply the reviewed v2.3.1 observations to the one fixed v2.3.2 candidate.

This local WSL helper reads GitHub metadata/configuration and writes a separate
private record. It does not run experiments, alter old evidence, set secrets,
change the Actions driver's pins, or prepare/publish an application.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

if __package__:
    from . import schema431_bundle as bundle
    from . import schema431_prepare as driver
else:
    import schema431_bundle as bundle
    import schema431_prepare as driver

CURRENT = "03cc463cf09192e1403f839df4165410c5db8d7b"
PREVIOUS = "c717ac6baaa3d7556120d2a7f6c9435f165f132b"
CANDIDATE = "f1a5ef49eeab41744635232cddd51c2257871aed"
TOOLING = "64225b82c9b2e978409f0b35490be3c83af3f157"
PREVIOUS_RECORD_SHA256 = "d384f6619038a2b55a30abf6b08ecd88d9d7aede5292963414fd52d433f9be4d"
PREVIOUS_ROOT = Path("/home/yuto/autonavlog-releases/schema4-5-v2.3.1-20261111")
DESTINATION = Path("/home/yuto/autonavlog-releases/schema4-5-v2.3.2-20261113")
CANDIDATE_CI = 43383649255
REVIEWED_BY = "GPT-6 Astra + GPT-6.1 Sol; source-equivalence applicability review, 2026-11-13"

# The complete, independently inspected c717 -> f1a difference. Every other
# tracked path is identical, including runtime, schema, SDK and build sources.
CHANGED_PATHS = (
    ".github/workflows/static-app-release.yml",
    ".github/workflows/test.yml",
    "AGENTS.md", "CHANGELOG.md", "VERSION",
    "docs/agent_workflow.md",
    "docs/evidence/ci/impact-selection-20261110.md",
    "docs/forecast_schema_transition.md", "docs/knowledge/INDEX.md",
    "docs/release-2-3-2-copy-request.json", "docs/schema431_actions_prepare.md",
    "docs/static_operations.md", "docs/testing.md",
    "scripts/check_ci_results.py", "scripts/ci_changes.py",
    "scripts/static_ops/schema423_readback.py", "scripts/static_ops/schema431_bundle.py",
    "scripts/static_ops/schema431_diagnostics.py", "scripts/static_ops/schema431_prepare.py",
    "scripts/static_ops/schema431_publish.py",
    "tests/integration/check_ci_changes.py", "tests/integration/check_ci_gate.py",
    "tests/integration/check_schema431_tooling.py",
    "tests/integration/check_static_tooling_install.py",
    "tests/unit/test_account_sync_ci.py", "tests/unit/test_release_automation.py",
    "tests/unit/test_schema423_readback.py", "tests/unit/test_schema431_diagnostics.py",
    "tests/unit/test_schema431_prepare.py", "tests/unit/test_schema431_publish.py",
    "web/e2e/static-production.spec.ts",
)


def read_only_operator(app, root: Path):
    class EvidenceReader(app.Operator):
        def gh(self, endpoint, method="GET", body=None):
            bundle.require(method == "GET" and body is None, "github-read-only")
            return super().gh(endpoint, method, body)

    return EvidenceReader(root)


def check_sources(operator) -> dict:
    bundle.require(operator.git("rev-parse", "HEAD") == TOOLING, "tooling-identity")
    changed = operator.git("diff", "--no-ext-diff", "--no-renames", "--name-only",
                           PREVIOUS, CANDIDATE).splitlines()
    bundle.require(changed == sorted(CHANGED_PATHS), "unreviewed-source-difference")
    for tag, sha, version in (("v2.3.1", PREVIOUS, "2.3.1"),
                              ("v2.3.2", CANDIDATE, "2.3.2")):
        operator.git("fetch", "origin", f"refs/tags/{tag}")
        bundle.require(operator.git("rev-parse", "FETCH_HEAD^{commit}") == sha
                       and operator.git("show", sha + ":VERSION") == version,
                       "release-source-identity")
    return {
        "previous_sha": PREVIOUS, "candidate_sha": CANDIDATE, "tooling_sha": TOOLING,
        "previous_tree": operator.git("rev-parse", PREVIOUS + "^{tree}"),
        "candidate_tree": operator.git("rev-parse", CANDIDATE + "^{tree}"),
        "changed_paths": changed,
        "basis": "Runtime, storage/sync, schema, data, Rules/indexes, SDK dependencies and "
                 "fixed build/publication sources are unchanged. VERSION and release notes "
                 "differ; production artifact bytes are not assumed identical.",
    }


def check_release(operator) -> None:
    release = operator.gh("releases/tags/v2.3.2")
    bundle.require(release.get("tag_name") == "v2.3.2" and release.get("draft") is False
                   and release.get("prerelease") is False and release.get("published_at"),
                   "stable-release-required")
    run = operator.gh("actions/runs/" + str(CANDIDATE_CI))
    bundle.require(run.get("head_sha") == CANDIDATE and run.get("status") == "completed"
                   and run.get("conclusion") == "success"
                   and run.get("path") == ".github/workflows/test.yml"
                   and run.get("repository", {}).get("id") == driver.REPO_ID,
                   "candidate-ci-not-successful")


def private_path(path: Path, root: Path) -> None:
    bundle.require(path.is_relative_to(root) and path.resolve() == path,
                   "evidence-path-or-symlink")
    for parent in (root, *root.parents):
        bundle.require(not parent.is_symlink(), "evidence-path-or-symlink")


def original_evidence() -> tuple[dict, dict[str, bytes]]:
    path = PREVIOUS_ROOT / bundle.RECORD_NAME
    private_path(path, PREVIOUS_ROOT)
    raw = bundle.read_file(path, bundle.MAX_RECORD, private=True)
    bundle.require(bundle.sha256(raw) == PREVIOUS_RECORD_SHA256, "original-record-hash")
    record = json.loads(raw)
    bundle.require(record.get("sha") == PREVIOUS and record.get("current_sha") == CURRENT
                   and record.get("tooling_sha") == TOOLING, "original-record-identity")
    reports = {}
    for role in bundle.ROLES:
        path = PREVIOUS_ROOT / record["checks"][role]["record"]["path"]
        private_path(path, PREVIOUS_ROOT)
        reports[role] = bundle.read_file(path, bundle.MAX_REPORT, private=True)
        bundle.require(bundle.sha256(reports[role]) == record["checks"][role]["record"]["sha256"],
                       "original-report-hash")
    return record, reports


def write_reapplication(operator, variables: dict, original: dict,
                        reports: dict[str, bytes], source_review: dict) -> str:
    """The fixed validator must accept the originals before any new PASS is written."""
    operator.schema_transition = PREVIOUS_ROOT / bundle.RECORD_NAME
    receipt = operator.reviewed_schema(PREVIOUS, CURRENT, variables)
    bundle.require(receipt["sha256"] == PREVIOUS_RECORD_SHA256
                   and set(receipt["evidence"]) == set(bundle.ROLES)
                   and receipt["record"] == original, "original-validator-receipt")
    for role, raw in reports.items():
        bundle.require(bundle.sha256(raw) == receipt["evidence"][role]["sha256"],
                       "original-report-changed")

    identity = {key: value for key, value in original.items() if key != "checks"}
    identity["sha"] = CANDIDATE
    record = {**identity, "checks": {}}
    contents = {}
    for role in bundle.ROLES:
        summary = (
            f"Reapplied the reviewed v2.3.1 {role} observations to v2.3.2 after exact "
            "source/SDK equivalence review. No new experiment is claimed. Original limits "
            "and the accepted own-device Latest replacement policy remain unchanged."
        )
        report = {
            "identity": identity, "check": role, "result": "PASS",
            "reviewed_by": REVIEWED_BY, "summary": summary,
            "source_record_sha256": PREVIOUS_RECORD_SHA256,
            "source_report_sha256": bundle.sha256(reports[role]),
            "source_report": json.loads(reports[role]),
            "applicability_review": source_review,
            "candidate_ci": CANDIDATE_CI,
            "limits": "This attests only to reuse of previously reviewed compatibility "
                      "observations. Fresh production readback, isolated build/static E2E, "
                      "plan review and digest-specific publish approval are still required.",
        }
        name = role + ".json"
        contents[name] = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
                          + "\n").encode()
        bundle.require(len(contents[name]) <= bundle.MAX_REPORT, "new-report-size")
        record["checks"][role] = {
            "result": "PASS", "reviewed_by": REVIEWED_BY, "summary": summary,
            "record": {"path": name, "sha256": bundle.sha256(contents[name])},
        }
    contents[bundle.RECORD_NAME] = (json.dumps(record, ensure_ascii=False, sort_keys=True,
                                              indent=2) + "\n").encode()
    bundle.require(len(contents[bundle.RECORD_NAME]) <= bundle.MAX_RECORD, "new-record-size")
    private_path(DESTINATION, DESTINATION)
    DESTINATION.mkdir(mode=0o700, exist_ok=False)
    try:
        for name, raw in contents.items():
            bundle.write_private(DESTINATION / name, raw)
        operator.schema_transition = DESTINATION / bundle.RECORD_NAME
        accepted = operator.reviewed_schema(CANDIDATE, CURRENT, variables)
        digest = bundle.sha256(contents[bundle.RECORD_NAME])
        bundle.require(accepted["sha256"] == digest
                       and set(accepted["evidence"]) == set(bundle.ROLES),
                       "new-validator-receipt")
        return digest
    except Exception:
        # Only the directory exclusively created by this invocation is removed.
        shutil.rmtree(DESTINATION)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tooling", type=Path, required=True)
    args = parser.parse_args(argv)
    previous_umask, stage = os.umask(0o077), "tooling"
    try:
        bundle.require(bundle.TOOLING == TOOLING, "tooling-identity")
        app = driver.load_tooling(args.tooling)
        operator = read_only_operator(app, args.tooling.resolve())
        stage = "source-equivalence"
        source_review = check_sources(operator)
        stage = "candidate-release-ci"
        check_release(operator)
        stage = "original-evidence"
        original, reports = original_evidence()
        stage = "public-configuration"
        variables = operator.variables()
        stage = "fixed-validator-and-reapplication"
        digest = write_reapplication(operator, variables, original, reports, source_review)
        print(json.dumps({"status": "ACCEPTED", "record_sha256": digest}))
        return 0
    except Exception:
        # Provider responses, private paths/configuration and report contents
        # must never escape through tracebacks or command output.
        print(json.dumps({"status": "BLOCKED", "stage": stage}))
        return 1
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    sys.exit(main())
