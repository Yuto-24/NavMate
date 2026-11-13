"""Dispatch-only #431 prepare adapter. Never publish, resume, or change Rules.

The driver lives on main; all schema, snapshot and build gates execute from the
separately checked-out, reviewed tooling commit. No reviewed file is patched.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from . import schema431_bundle as bundle
    from . import schema431_diagnostics as diagnostics
else:
    import schema431_bundle as bundle
    import schema431_diagnostics as diagnostics

REPO = "Yuto-24/NavMate"
WORKFLOW = ".github/workflows/static-app-release.yml"
REPO_ID, OWNER_ID = 1314030412, 65487096
CANDIDATE_CI = 43383649255
OPERATION = "prepare-schema431"


def scope(env: dict, event: dict, *, operation: str = OPERATION,
          job: str = "manual-prepare") -> None:
    repository = event.get("repository", {})
    inputs = event.get("inputs", {})
    bundle.require(
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and env.get("GITHUB_REPOSITORY") == REPO
        and env.get("GITHUB_REPOSITORY_ID") == str(REPO_ID)
        and env.get("GITHUB_REPOSITORY_OWNER_ID") == str(OWNER_ID)
        and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_WORKFLOW_REF") == REPO + "/" + WORKFLOW + "@refs/heads/main"
        and env.get("GITHUB_WORKFLOW_SHA") == env.get("GITHUB_SHA")
        and env.get("GITHUB_JOB") == job
        and re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", ""))
        and all(re.fullmatch(r"[1-9]\d{0,19}", env.get(name, ""))
                for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
        and repository.get("id") == REPO_ID
        and repository.get("full_name") == REPO and repository.get("private") is False
        and repository.get("owner", {}).get("id") == OWNER_ID
        and inputs.get("operation") == operation and inputs.get("release_id", "") == "",
        "dispatch-scope",
    )


def checked_checkout(root: Path, expected: str) -> None:
    for args, allowed in (
        (["rev-parse", "HEAD"], {expected}),
        (["status", "--porcelain", "--untracked-files=all"], {""}),
        (["remote", "get-url", "origin"], {"https://github.com/" + REPO,
                                         "https://github.com/" + REPO + ".git",
                                         "git@github.com:" + REPO + ".git"}),
    ):
        result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                text=True, check=True, timeout=30)
        bundle.require(result.stdout.strip() in allowed, "checkout-identity-or-cleanliness")


def load_tooling(root: Path):
    root = root.resolve()
    # Check before import: a dirty module must never execute with provider access.
    checked_checkout(root, bundle.TOOLING)
    sys.path[:0] = [str(root), str(root / "src")]
    app = importlib.import_module("scripts.static_ops.app_release")
    bundle.require(Path(app.__file__).resolve() == root / "scripts/static_ops/app_release.py"
                   and Path(app.gate.__file__).resolve()
                   == root / "scripts/static_ops/publication_gate.py", "tooling-import")
    return app


def manual_operator(app, root: Path, env: dict):
    class ManualOperator(app.Operator):
        pause_allowed = False

        def gh(self, endpoint, method="GET", body=None):
            app.require(method == "GET" or (
                self.pause_allowed and method == "PATCH"
                and endpoint == "actions/variables/STATIC_AUTOMATION_ENABLED"
                and body == {"name": "STATIC_AUTOMATION_ENABLED", "value": "false"}),
                "Only the preflight-authorized automation pause is permitted")
            return super().gh(endpoint, method, body)

        def set_workflow(self, enabled):
            raise app.Blocked("Workflow mutation is outside prepare")

        def upload(self, *args):
            raise app.Blocked("Publication is outside prepare")

        def own_run(self, run, workflow_id):
            app.require(
                run.get("id") == int(env["GITHUB_RUN_ID"])
                and type(run.get("run_attempt")) is int
                and run.get("run_attempt") == int(env["GITHUB_RUN_ATTEMPT"])
                and run.get("workflow_id") == workflow_id
                and run.get("path") == WORKFLOW and run.get("event") == "workflow_dispatch"
                and run.get("status") == "in_progress" and run.get("head_branch") == "main"
                and run.get("head_sha") == env["GITHUB_SHA"]
                and run.get("repository", {}).get("id") == REPO_ID
                and run.get("repository", {}).get("full_name") == REPO
                and run.get("repository", {}).get("owner", {}).get("id") == OWNER_ID
                and run.get("head_repository", {}).get("id") == REPO_ID,
                "Exact main dispatch run identity required")

        def idle(self):
            app_workflow = self.gh("actions/workflows/" + app.APP_WORKFLOW)
            app.require(app_workflow.get("path") == WORKFLOW
                        and app_workflow.get("state") == "active"
                        and type(app_workflow.get("id")) is int and app_workflow["id"] > 0,
                        "Active app workflow identity required")
            identity = app_workflow["id"]
            self.own_run(self.gh("actions/runs/" + env["GITHUB_RUN_ID"]), identity)
            # Preserve the pinned complete inventory check for every feed run.
            self.workflow_idle(app.WORKFLOW)
            page, count, seen, own_seen = 1, None, set(), False
            while True:
                value = self.gh(
                    f"actions/workflows/{app.APP_WORKFLOW}/runs?per_page=100&page={page}")
                rows, total = value["workflow_runs"], value["total_count"]
                app.require(type(total) is int and total >= 0 and isinstance(rows, list)
                            and (count is None or count == total), "Workflow inventory changed")
                count = total
                for row in rows:
                    run_id = row.get("id")
                    app.require(type(run_id) is int and run_id > 0 and run_id not in seen,
                                "Invalid or duplicate workflow run")
                    seen.add(run_id)
                    if run_id == int(env["GITHUB_RUN_ID"]):
                        self.own_run(row, identity)
                        own_seen = True
                    else:
                        app.require(row.get("status") == "completed",
                                    "Another publication run is not idle")
                app.require(len(seen) <= total, "Invalid workflow inventory")
                if len(seen) == total:
                    break
                app.require(len(rows) == 100, "Incomplete workflow inventory")
                page += 1
            app.require(own_seen, "Own run missing from complete inventory")
            self.own_run(self.gh("actions/runs/" + env["GITHUB_RUN_ID"]), identity)

        def reviewed_schema(self, sha, current, variables):
            app.require(bundle.sha256(bundle.read_file(self.schema_transition, bundle.MAX_RECORD))
                        == bundle.RECORD_SHA256, "Original schema record changed")
            return super().reviewed_schema(sha, current, variables)

        def build(self, sha, snapshot, destination):
            # Git checkout modes survive the container's static asset copies.
            # Keep the parent private while allowing the nonroot host to read
            # root-owned outputs from the unchanged reviewed build and tests.
            info = destination.parent.lstat()
            app.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                        and info.st_mode & 0o077 == 0, "Private build parent required")
            previous_umask = os.umask(0o022)
            try:
                return super().build(sha, snapshot, destination)
            finally:
                os.umask(previous_umask)

        def snapshot(self, sha, current, *, paused=False):
            app.require(sha == bundle.CANDIDATE and current == bundle.CURRENT
                        and self.git("rev-parse", "HEAD") == bundle.TOOLING and not paused,
                        "Only the pinned prepare identities are permitted")
            return super().snapshot(sha, current, paused=paused)

    return ManualOperator(root, schema_transition=bundle.EVIDENCE_ROOT / bundle.RECORD_NAME)


def before_pause(app, operator):
    class ReadOnlySnapshot(type(operator)):
        def compatibility(self, sha, current, variables):
            receipt = operator.compatibility(sha, current, variables)
            self.schema_receipt = operator.schema_receipt
            self.rules_receipt = operator.rules_receipt
            return receipt

    # Only this read-only snapshot may observe automation=true. Its compatibility
    # call still validates the actual schema record with the unchanged pinned gate.
    reader = ReadOnlySnapshot(operator.root)
    reader.env = operator.env
    return reader.snapshot(bundle.CANDIDATE, bundle.CURRENT)


def check_candidate(app, operator):
    selected = operator.gh("releases/tags/v2.3.2")
    app.require(selected.get("tag_name") == "v2.3.2" and selected.get("draft") is False
                and selected.get("prerelease") is False and selected.get("published_at"),
                "Existing stable v2.3.2 Release required")
    operator.git("fetch", "origin", "refs/tags/v2.3.2")
    app.require(operator.git("rev-parse", "FETCH_HEAD^{commit}") == bundle.CANDIDATE
                and operator.git("show", bundle.CANDIDATE + ":VERSION") == "2.3.2",
                "Pinned candidate tag or VERSION changed")
    run = operator.gh("actions/runs/" + str(CANDIDATE_CI))
    app.require(run.get("head_sha") == bundle.CANDIDATE and run.get("status") == "completed"
                and run.get("conclusion") == "success"
                and run.get("path") == ".github/workflows/test.yml"
                and run.get("repository", {}).get("id") == REPO_ID,
                "Pinned candidate CI must still be successful")


def public_status(path: Path, value: dict) -> None:
    # Atomic bounded status, with no receipt/configuration/provider values.
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, sort_keys=True)
    temporary.replace(path)


def quiet_journal(app, store: Path, status_path: Path):
    class QuietJournal(app.Journal):
        def save(self):
            super().save()
            public_status(status_path, {
                "status": self.value["status"], "stage": self.value["stage"],
                "automation": self.value["changes"]["automation"],
                "automation_before": self.value.get("automation_before", "UNKNOWN"),
                "archive_ready": False,
            })

        def finish(self, success):
            # Pinned Journal.finish prints private receipts. Retain the same
            # journal locally, but never send its body to Actions logs/summary.
            self.value["status"] = "OK" if success else "BLOCKED"
            self.value["required_action"] = (
                "Review exact plan digest; publish requires separate authorization"
                if success else "Read remote state; no automatic resume; prepare again in new store"
            )
            self.save()

    return QuietJournal(store / "prepare-status.json", "prepare", bundle.CANDIDATE)


def execute(app, operator, store: Path, journal) -> dict:
    check_candidate(app, operator)
    initial = before_pause(app, operator)
    journal.value["automation_before"] = initial["variables"]["STATIC_AUTOMATION_ENABLED"]
    journal.save()
    # The last read before mutation includes canonical/config, both workflows,
    # complete Pages inventory, live Rules and the original reviewed evidence.
    app.unchanged(initial, before_pause(app, operator), deployment=True)
    journal.stage("pause")
    if initial["variables"]["STATIC_AUTOMATION_ENABLED"] == "true":
        operator.pause_allowed = True
        try:
            journal.mutation("automation", lambda: operator.set_variable(
                "STATIC_AUTOMATION_ENABLED", "false"))
        finally:
            operator.pause_allowed = False
    journal.stage("paused-readback")
    app.unchanged(initial, operator.snapshot(bundle.CANDIDATE, bundle.CURRENT),
                  paused=True, deployment=True)
    # No patched validator/build and no policy-authorized publication call.
    plan = app.prepare(operator, bundle.CANDIDATE, bundle.CURRENT, store, journal)
    journal.finish(True)
    return plan


def locations(env: dict) -> tuple[Path, Path, Path]:
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        bundle.require(re.fullmatch(r"[1-9]\d{0,19}", env.get(name, "")), "run-path")
    temporary = Path(env["RUNNER_TEMP"]).resolve()
    suffix = env["GITHUB_RUN_ID"] + "-" + env["GITHUB_RUN_ATTEMPT"]
    return (temporary / ("schema431-private-" + suffix),
            temporary / ("schema431-result-" + suffix + ".aesgcm"),
            temporary / ("schema431-status-" + suffix + ".json"))


def cleanup_store(store: Path, env: dict) -> None:
    expected, _, _ = locations(env)
    info = store.lstat()
    bundle.require(store == expected and stat.S_ISDIR(info.st_mode)
                   and not store.is_symlink() and info.st_uid == os.getuid()
                   and info.st_mode & 0o077 == 0, "cleanup-scope")
    try:
        shutil.rmtree(store)
    except PermissionError:
        # The pinned Docker build leaves root-owned 0755 subdirectories. Limit
        # privileged deletion to this invocation's exclusive private store.
        subprocess.run(["sudo", "-n", "rm", "-rf", "--", str(store)], cwd="/",
                       env={"PATH": os.defpath}, capture_output=True, check=True, timeout=120)
    bundle.require(not store.exists() and not store.is_symlink(), "cleanup-incomplete")


def run(root: Path) -> int:
    """Keep this run private without changing the caller's later file permissions."""
    previous_umask = os.umask(0o077)
    try:
        return _run_private(root)
    finally:
        os.umask(previous_umask)


def _run_private(root: Path) -> int:
    # Transport material is never inherited by provider/producer subprocesses.
    encoded = os.environ.pop("SCHEMA431_EVIDENCE", "")
    encoded_key = os.environ.pop("SCHEMA431_ARCHIVE_KEY", "")
    env = dict(os.environ)
    store, output, status_path = locations(env)
    public_status(status_path, {"status": "BLOCKED", "stage": "scope",
                               "automation": "UNCHANGED", "automation_before": "UNKNOWN",
                               "archive_ready": False})
    journal, evidence, key = None, None, None
    created_store, created_evidence = False, False
    success, archive_ready = False, False
    plan_digest = None
    try:
        scope(env, json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text()))
        checked_checkout(Path(__file__).resolve().parents[2], env["GITHUB_SHA"])
        bundle.require(all(env.get(name) for name in (
            "GH_TOKEN", "CLOUDFLARE_API_TOKEN", "STATIC_GOOGLE_ACCESS_TOKEN")), "credentials")
        bundle.require(all(shutil.which(name) for name in ("gh", "git", "docker", "node")),
                       "runner-tools")
        key = bundle.key_bytes(encoded_key)
        evidence = bundle.open_secret(encoded, key, datetime.now(UTC))
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        cipher = AESGCM(key)
        bundle.require(cipher.decrypt(nonce, cipher.encrypt(nonce, b"probe", bundle.MAGIC),
                                      bundle.MAGIC) == b"probe", "archive-crypto")
        app = load_tooling(root)
        store.mkdir(mode=0o700, exist_ok=False)
        created_store = True
        journal = quiet_journal(app, store, status_path)
        bundle.restore_evidence(evidence)
        created_evidence = True
        operator = manual_operator(app, root.resolve(), env)
        plan = execute(app, operator, store, journal)
        plan_digest = bundle.sha256((store / "plan.json").read_bytes())
        success = True
    except Exception as error:
        if journal is not None:
            journal.finish(False)
            diagnostics.record_failure(app, error, root.resolve(), journal, env)
    finally:
        try:
            if journal is not None and evidence is not None and key is not None:
                handoff = {"schema_version": 1, "sha": bundle.CANDIDATE,
                           "current_sha": bundle.CURRENT, "tooling_sha": bundle.TOOLING,
                           "driver_sha": env["GITHUB_SHA"], "run_id": env["GITHUB_RUN_ID"],
                           "run_attempt": env["GITHUB_RUN_ATTEMPT"], "prepared": success,
                           "plan_sha256": plan_digest,
                           "prepared_at": plan["prepared_at"] if success else None}
                app.write_json(store / "handoff.json", handoff)
                try:
                    bundle.seal(store, evidence, key, output, success=success)
                    archive_ready = True
                except Exception:
                    success = False
        finally:
            # Even a handoff/status write failure must reach output and cleanup.
            # Actions can upload the encrypted result after a failed step, too.
            try:
                with Path(env["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
                    stream.write("archive_ready=" + str(archive_ready).lower() + "\n")
            finally:
                cleanup_ok = True
                if created_evidence:
                    try:
                        shutil.rmtree(bundle.EVIDENCE_ROOT)
                    except Exception:
                        cleanup_ok = False
                if created_store:
                    try:
                        cleanup_store(store, env)
                    except Exception:
                        cleanup_ok = False
                status = json.loads(status_path.read_text())
                if journal is not None:
                    prepared = success and archive_ready
                    status.update(status="PREPARED" if prepared else "BLOCKED",
                                  archive_ready=archive_ready,
                                  archive_status="READY" if archive_ready else "FAILED",
                                  plan_sha256=plan_digest if prepared else None)
                status["cleanup"] = "COMPLETE" if cleanup_ok else "FAILED"
                if not cleanup_ok:
                    success = False
                    status.update(status="BLOCKED", stage="cleanup")
                public_status(status_path, status)
    return 0 if success and archive_ready else 1


def report() -> None:
    _, _, status_path = locations(dict(os.environ))
    if status_path.is_file():
        status = json.loads(status_path.read_text())
    else:
        status = {"status": "NOT_STARTED", "automation": "UNCHANGED"}
    status["archive_upload"] = os.environ.get("ARCHIVE_UPLOAD_OUTCOME", "unknown")
    if status.get("status") == "PREPARED" and status["archive_upload"] != "success":
        status.update(status="BLOCKED", stage="archive-upload")
    # Only the bounded status file is eligible for public display. Provider errors,
    # schema records, journals, plan bodies and configuration never enter it.
    print(json.dumps(status, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "report"))
    parser.add_argument("--tooling", type=Path)
    args = parser.parse_args()
    if args.mode == "report":
        report()
        return 0
    bundle.require(args.tooling is not None, "tooling-path")
    return run(args.tooling)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        sys.exit("Schema431 prepare BLOCKED; use bounded status and private recovery record")
