"""Collect exact-source CI and actual-version evidence, without claiming review."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.static_ops import app_release as app
from scripts.static_ops import release_ci_gate, release_preflight, source_ci

AIP = "aip-reference-source-writer-fence"


def browser_ci(operator, sha, receipt):
    tooling = operator.git("rev-parse", "HEAD")
    for path in (
        ".github/workflows/test.yml",
        "scripts/run_account_sync_suite.sh",
        "firebase.json",
        "web/package.json",
        "web/package-lock.json",
        "web/e2e",
        "web/scripts",
        "tests/integration",
        "web/playwright.storage-upgrade.config.ts",
        "web/playwright.firestore.config.ts",
        "web/playwright.migration.config.ts",
        "web/vite.storage-upgrade.config.ts",
        "web/vite.config.ts",
    ):
        app.require(
            operator.source_digest(sha, path) == operator.source_digest(tooling, path),
            "Candidate migration tests differ from the trusted evidence recipe",
        )
    jobs, total = [], None
    for page in range(1, 5):
        response = operator.gh(
            f"actions/runs/{receipt['run_id']}/attempts/{receipt['run_attempt']}/jobs"
            f"?per_page=100&page={page}"
        )
        count, rows = response["total_count"], response["jobs"]
        app.require(
            type(count) is int
            and count > 0
            and isinstance(rows, list)
            and (total is None or total == count),
            "CI job inventory changed",
        )
        total = count
        jobs.extend(rows)
        app.require(
            len({job["id"] for job in jobs}) == len(jobs) <= count,
            "Duplicate or incomplete CI jobs",
        )
        if len(jobs) == count:
            break
        app.require(len(rows) == 100, "Incomplete CI jobs")
    else:
        raise app.Blocked("CI job inventory limit exceeded")
    matches = [job for job in jobs if job.get("name") == "account-sync-tests (contracts, 1)"]
    app.require(
        len(matches) == 1 and source_ci.successful(matches[0]),
        "Real SDK and storage migration tests must execute successfully",
    )
    steps = [
        step
        for step in matches[0].get("steps", [])
        if step.get("name") == "Verify real SDK, Rules and cross-device Local-first workflows"
    ]
    app.require(
        len(steps) == 1 and source_ci.successful(steps[0]),
        "Migration test step was skipped or failed",
    )
    app.require(
        source_ci.require_success(operator.gh, sha) == receipt,
        "Source CI attempt changed during evidence collection",
    )
    return {**receipt, "job_id": matches[0]["id"]}


def browser_sources(operator, sha, current):
    prefix = "web/e2e/fixtures/pre-aip/"
    provenance = json.loads(operator.git("show", sha + ":" + prefix + "provenance.json"))
    expected = {
        "localProjectRepository.ts",
        "accountProjectRepository.ts",
        "firestoreSyncRepository.ts",
    }
    app.require(set(provenance["files"]) == expected, "Unsupported old browser fixture")
    result = {}
    for name, digest in provenance["files"].items():
        actual = operator.source_digest(current, "web/src/" + name)
        frozen = operator.source_digest(sha, prefix + name)
        app.require(actual == frozen, "Old browser fixture does not represent production")
        result[name] = {"current_blob": actual, "fixture_blob": frozen, "fixture_sha256": digest}
    app.require(
        operator.source_digest(current, "web/package-lock.json")
        == operator.source_digest(sha, "web/package-lock.json"),
        "Old-client SDK dependency changed",
    )
    runtime = app.command(
        [
            "node",
            str(operator.root / "scripts/static_ops/check_migration_browser.mjs"),
            current,
            sha,
        ],
        cwd=operator.root,
        env={key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ},
    )
    result["shared_runtime"] = json.loads(runtime)
    return result


def actual_versions(operator, sha, current, directory: Path):
    probe = operator.root / "scripts/static_ops/migration_probe.py"
    clean_env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    images = []
    try:
        for label, commit in (("current", current), ("candidate", sha)):
            checkout = directory / label
            app.command(
                [
                    "git",
                    "clone",
                    "--no-hardlinks",
                    "--no-checkout",
                    str(operator.root),
                    str(checkout),
                ],
                env=clean_env,
            )
            app.command(["git", "checkout", "--detach", commit], cwd=checkout, env=clean_env)
            image = "navmate-migration-" + label + ":" + os.environ["GITHUB_RUN_ID"]
            images.append(image)
            app.command(
                ["docker", "build", "--target", "test", "--tag", image, "."],
                cwd=checkout,
                env=clean_env,
                timeout=1800,
            )
        common = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            "--env",
            "PYTHONOPTIMIZE=0",
            "--mount",
            f"type=bind,source={probe},target=/migration_probe.py,readonly",
        ]
        raw = app.command(
            [*common, images[0], "/migration_probe.py", "generate"],
            env=clean_env,
            timeout=300,
        )
        sample = directory / "old-records.json"
        sample.write_text(raw)
        checked = app.command(
            [
                *common,
                "--mount",
                f"type=bind,source={sample},target=/old-records.json,readonly",
                images[1],
                "/migration_probe.py",
                "verify",
                "/old-records.json",
            ],
            env=clean_env,
            timeout=300,
        )
        result = json.loads(checked)
        app.require(result.get("result") == "PASS", "Actual-version preservation failed")
        return {
            **result,
            "sample_sha256": app.digest(raw.encode()),
            "sample_json": raw,
        }
    finally:
        original_failure = sys.exc_info()[0] is not None
        cleanup_failed = False
        for image in images:
            # A timeout may have created a tag. Register before building, then use
            # Docker's successful inventory (not an inspect error) to prove absence.
            try:
                present = app.command(
                    ["docker", "image", "ls", "--quiet", "--filter", "reference=" + image],
                    env=clean_env, timeout=60,
                ).strip()
                if present:
                    app.command(["docker", "image", "rm", image], env=clean_env, timeout=60)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            if not original_failure:
                raise app.Blocked("Migration image cleanup failed")
            print("Migration image cleanup incomplete; reconcile invocation tags", file=sys.stderr)


def collect(operator, sha, directory):
    variables = operator.variables()
    current = variables["STATIC_APPROVED_SHA"]
    route = release_preflight.inspect(operator, sha, current)
    app.require(
        route["route"] == "MANUAL" and route["kind"] == AIP,
        "This migration has no automated evidence recipe; individual review required",
    )
    app.require(
        variables["STATIC_ORIGIN"] == app.gate.ORIGIN
        and app.public_configuration(variables)
        == app.release(app.gate.ORIGIN, current)["configuration"],
        "Production configuration mismatch",
    )
    # A full push CI, including real SDK/emulator/browser tests, is required.
    # A PR impact-selected run cannot substitute for this evidence.
    receipt = browser_ci(operator, sha, release_ci_gate.await_source_ci(operator.gh, sha))
    fixtures = browser_sources(operator, sha, current)
    domain = actual_versions(operator, sha, current, directory)
    app.require(
        operator.variables() == variables, "Configuration changed during evidence collection"
    )
    app.require(
        release_preflight.inspect(operator, sha, current) == route,
        "Production or source changed during evidence collection",
    )
    identity = {
        "schema_version": 1,
        "kind": AIP,
        "sha": sha,
        "current_sha": current,
        "tooling_sha": route["tooling_sha"],
        "project": variables["VITE_FIREBASE_PROJECT_ID"],
        "origin": app.gate.ORIGIN,
        "configuration_digest": route["configuration_digest"],
        "direction": "old-to-new",
        "recovery": "forward-fix; preserve Project data",
        "database_version": 3,
        "before_blob": operator.source_digest(current, release_preflight.SCHEMA),
        "after_blob": operator.source_digest(sha, release_preflight.SCHEMA),
        "writer_blob": operator.source_digest(sha, release_preflight.WRITER),
    }
    sample_json = domain.pop("sample_json")
    return {
        "sample_json": sample_json,
        "schema_version": 1,
        "phase": "evidence",
        "result": "PASS",
        "publication_authorized": False,
        "candidate_sha": sha,
        "identity": identity,
        "created_at": datetime.now(UTC).isoformat(),
        "origin_run": app.release_review.identity(dict(os.environ)),
        "checks": {
            "old_to_new": {
                "result": "PASS",
                "summary": (
                    "Actual old-version records read by candidate; "
                    "IDs, draft and historical calculations retained."
                ),
                "observations": domain,
            },
            "old_writer_fenced": {
                "result": "PASS",
                "summary": (
                    "Exact production browser adapters covered by full push CI "
                    "storage-upgrade tests; "
                    "independent source review still required."
                ),
                "observations": {"source_ci": receipt, "fixtures": fixtures},
            },
            "storage_sync_roundtrip": {
                "result": "PASS",
                "summary": (
                    "Full push CI real IndexedDB and SDK/emulator roundtrip; synthetic identities, "
                    "not live account or real-device acceptance."
                ),
                "observations": {"source_ci": receipt},
            },
        },
    }
