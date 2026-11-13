"""Publish only an explicitly approved #431 plan through the fixed reviewed tooling."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

if __package__:
    from . import schema431_bundle as bundle
    from . import schema431_prepare as prepare
else:
    import schema431_bundle as bundle
    import schema431_prepare as prepare

OPERATION = "publish-schema431"


def scope(env: dict, event: dict) -> dict:
    prepare.scope(env, event, operation=OPERATION, job="manual-publish")
    inputs = event["inputs"]
    bundle.require(env["GITHUB_RUN_ATTEMPT"] == "1"
                   and all(re.fullmatch(r"[1-9]\d{0,19}", inputs.get(name, ""))
                           for name in ("prepare_run_id", "prepare_run_attempt"))
                   and inputs["prepare_run_id"] != env["GITHUB_RUN_ID"]
                   and re.fullmatch(r"[0-9a-f]{64}", inputs.get("reviewed_plan_sha256", "")),
                   "explicit-plan-approval")
    return inputs


def publication_operator(app, root: Path, env: dict):
    # Inherit the exact own-run exception, complete idle inventories and original
    # schema-record check. Only the publish-specific capabilities differ.
    parent = type(prepare.manual_operator(app, root, env))

    class PublicationOperator(parent):
        publication_allowed = False

        def gh(self, endpoint, method="GET", body=None):
            allowed = (
                method == "PATCH" and (
                    endpoint == "actions/variables/STATIC_AUTOMATION_ENABLED"
                    and body == {"name": "STATIC_AUTOMATION_ENABLED", "value": "false"}
                    or endpoint == "actions/variables/STATIC_APPROVED_SHA"
                    and body == {"name": "STATIC_APPROVED_SHA", "value": bundle.CANDIDATE})
                or method == "PUT" and body is None and endpoint in (
                    "actions/workflows/" + app.WORKFLOW + "/disable",
                    "actions/workflows/" + app.WORKFLOW + "/enable"))
            app.require(method == "GET" or self.publication_allowed and allowed,
                        "Only the approved fixed publication mutations are permitted")
            return app.Operator.gh(self, endpoint, method, body)

        def set_workflow(self, enabled):
            return app.Operator.set_workflow(self, enabled)

        def upload(self, destination, sha, upload_env):
            app.require(self.publication_allowed and sha == bundle.CANDIDATE,
                        "Explicit fixed publication required")
            return app.Operator.upload(self, destination, sha, upload_env)

        def snapshot(self, sha, current, *, paused=False):
            app.require(sha == bundle.CANDIDATE and current == bundle.CURRENT
                        and self.git("rev-parse", "HEAD") == bundle.TOOLING,
                        "Only the pinned publication identities are permitted")
            return app.Operator.snapshot(self, sha, current, paused=paused)

    return PublicationOperator(root, schema_transition=bundle.EVIDENCE_ROOT / bundle.RECORD_NAME)


def source_run(operator, inputs: dict) -> dict:
    """Reject failed, replaced, rerunning, foreign or non-prepare source attempts."""
    run_id, attempt = inputs["prepare_run_id"], inputs["prepare_run_attempt"]
    run = operator.gh("actions/runs/" + run_id)
    workflow = operator.gh("actions/workflows/static-app-release.yml")
    repository = run.get("repository", {})
    bundle.require(
        type(run.get("id")) is int and run["id"] == int(run_id)
        and type(run.get("run_attempt")) is int and run["run_attempt"] == int(attempt)
        and run.get("status") == "completed" and run.get("conclusion") == "success"
        and run.get("event") == "workflow_dispatch" and run.get("head_branch") == "main"
        and run.get("path") == prepare.WORKFLOW
        and run.get("display_title") == "schema431-prepare"
        and re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", ""))
        and workflow.get("path") == prepare.WORKFLOW and workflow.get("state") == "active"
        and type(workflow.get("id")) is int and workflow["id"] > 0
        and run.get("workflow_id") == workflow["id"]
        and repository.get("id") == prepare.REPO_ID
        and repository.get("full_name") == prepare.REPO and repository.get("private") is False
        and repository.get("owner", {}).get("id") == prepare.OWNER_ID
        and run.get("head_repository", {}).get("id") == prepare.REPO_ID,
        "prepare-run-identity")
    jobs, seen, page, count = [], set(), 1, None
    while True:
        response = operator.gh(
            f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}")
        rows, total = response["jobs"], response["total_count"]
        bundle.require(type(total) is int and total > 0 and isinstance(rows, list)
                       and (count is None or count == total), "prepare-jobs-inventory")
        count = total
        for job in rows:
            job_id = job.get("id")
            # This endpoint selects the attempt; the job schema makes its echo optional.
            bundle.require(type(job_id) is int and job_id > 0 and job_id not in seen
                           and job.get("run_id") == int(run_id)
                           and ("run_attempt" not in job
                                or (type(job["run_attempt"]) is int
                                    and job["run_attempt"] == int(attempt)))
                           and job.get("head_sha") == run["head_sha"], "prepare-job-identity")
            seen.add(job_id)
            jobs.append(job)
        bundle.require(len(seen) <= total, "prepare-jobs-inventory")
        if len(seen) == total:
            break
        bundle.require(len(rows) == 100, "prepare-jobs-inventory")
        page += 1
    matches = [job for job in jobs if job.get("name") == "manual-prepare"]
    bundle.require(len(matches) == 1 and matches[0].get("status") == "completed"
                   and matches[0].get("conclusion") == "success", "prepare-job-result")
    return run


def download(operator, inputs: dict, store: Path) -> tuple[Path, dict]:
    run = source_run(operator, inputs)
    run_id, attempt = inputs["prepare_run_id"], inputs["prepare_run_attempt"]
    name = f"schema431-{run_id}-{attempt}"
    listing = operator.gh(f"actions/runs/{run_id}/artifacts?name={name}&per_page=100&page=1")
    rows = listing["artifacts"]
    # A name-filtered inventory must contain exactly one artifact, not a first match.
    bundle.require(type(listing["total_count"]) is int and listing["total_count"] == 1
                   and isinstance(rows, list) and len(rows) == 1, "prepare-artifact-inventory")
    artifact = rows[0]
    identity = artifact.get("workflow_run", {})
    bundle.require(type(artifact.get("id")) is int and artifact["id"] > 0
                   and artifact.get("name") == name and artifact.get("expired") is False
                   and type(artifact.get("size_in_bytes")) is int
                   and 0 < artifact["size_in_bytes"] <= bundle.MAX_ARCHIVE + 65536
                   and identity.get("id") == int(run_id)
                   and identity.get("repository_id") == prepare.REPO_ID
                   and identity.get("head_repository_id") == prepare.REPO_ID
                   and identity.get("head_branch") == "main"
                   and identity.get("head_sha") == run["head_sha"], "prepare-artifact-identity")
    zipped = store / "download.zip"
    with zipped.open("xb") as stream:
        subprocess.run([
            "gh", "api", "--hostname", "github.com", "--method", "GET",
            f"repos/{prepare.REPO}/actions/artifacts/{artifact['id']}/zip",
        ], env={**{key: operator.env[key] for key in ("PATH", "HOME", "GH_TOKEN")
                   if key in operator.env}, "GH_PROMPT_DISABLED": "1"},
            stdout=stream, stderr=subprocess.PIPE, check=True, timeout=180)
    bundle.require(zipped.stat().st_size <= bundle.MAX_ARCHIVE + 65536,
                   "prepare-artifact-capacity")
    expected = f"schema431-result-{run_id}-{attempt}.aesgcm"
    with zipfile.ZipFile(zipped) as archive:
        members = archive.infolist()
        bundle.require(len(members) == 1 and members[0].filename == expected
                       and 0 < members[0].file_size <= bundle.MAX_ARCHIVE,
                       "prepare-artifact-content")
        raw = archive.read(members[0])
    output = store / "prepare.aesgcm"
    bundle.write_private(output, raw)
    # A rerun/attempt change during download invalidates the handoff.
    bundle.require(source_run(operator, inputs) == run, "prepare-run-changed")
    return output, run


def validate_handoff(store: Path, handoff: dict, inputs: dict, source: dict) -> None:
    raw = bundle.read_file(store / "plan.json", bundle.MAX_RECORD, private=True)
    plan = json.loads(raw)
    bundle.require(handoff.get("prepared") is True and handoff.get("schema_version") == 1
                   and handoff.get("run_id") == inputs["prepare_run_id"]
                   and handoff.get("run_attempt") == inputs["prepare_run_attempt"]
                   and handoff.get("driver_sha") == source["head_sha"]
                   and handoff.get("plan_sha256") == inputs["reviewed_plan_sha256"]
                   and bundle.sha256(raw) == inputs["reviewed_plan_sha256"]
                   and handoff.get("prepared_at") == plan["prepared_at"]
                   and "publication" not in handoff
                   and not (store / "publish-status.json").exists(),
                   "approved-plan-handoff")
    created = datetime.fromisoformat(plan["prepared_at"])
    bundle.require(datetime.now(UTC) - timedelta(minutes=30) <= created <= datetime.now(UTC),
                   "plan-expired")


def quiet_journal(app, store: Path, status_path: Path):
    class PublicationJournal(app.Journal):
        def save(self):
            super().save()
            prepare.public_status(status_path, {
                "status": self.value["status"], "stage": self.value["stage"],
                "changes": self.value["changes"], "archive_ready": False,
            })

        def finish(self, success):
            self.value["status"] = "PUBLISHED" if success else "BLOCKED"
            self.value["required_action"] = (
                "Production acceptance and separately approved automation resume required"
                if success else "Read remote state; no automatic resume or rollback; do not rerun"
            )
            self.save()

    return PublicationJournal(store / "publish-status.json", "publish", bundle.CANDIDATE)


def execute(app, operator, store: Path, reviewed: str, journal) -> None:
    prepare.check_candidate(app, operator)
    operator.publication_allowed = True
    try:
        # The exact user-supplied digest is passed through; it is never inferred
        # from the downloaded plan or approved by the stable-release policy.
        app.publish(operator, bundle.CANDIDATE, bundle.CURRENT, store, reviewed, journal)
        journal.finish(True)
    finally:
        operator.publication_allowed = False


def run(root: Path) -> int:
    previous_umask = os.umask(0o077)
    try:
        return _run_private(root)
    finally:
        os.umask(previous_umask)


def _run_private(root: Path) -> int:
    encoded_key = os.environ.pop("SCHEMA431_ARCHIVE_KEY", "")
    env = dict(os.environ)
    store, output, status_path = prepare.locations(env)
    prepare.public_status(status_path, {"status": "BLOCKED", "stage": "scope",
                                       "archive_ready": False})
    created_store, reserved_evidence = False, False
    success, archive_ready = False, False
    journal, evidence, handoff = None, None, None
    restored = store / "plan"
    try:
        inputs = scope(env, json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text()))
        prepare.checked_checkout(Path(__file__).resolve().parents[2], env["GITHUB_SHA"])
        bundle.require(all(env.get(name) for name in (
            "GH_TOKEN", "CLOUDFLARE_API_TOKEN", "STATIC_GOOGLE_ACCESS_TOKEN")), "credentials")
        bundle.require(all(shutil.which(name) for name in ("gh", "git", "docker", "node")),
                       "runner-tools")
        key = bundle.key_bytes(encoded_key)
        app = prepare.load_tooling(root)
        operator = publication_operator(app, root.resolve(), env)
        store.mkdir(mode=0o700, exist_ok=False)
        created_store = True
        archive, source = download(operator, inputs, store)
        key_path = store / "archive.key"
        bundle.write_private(key_path, encoded_key.encode("ascii"))
        bundle.require(not bundle.EVIDENCE_ROOT.exists() and not bundle.EVIDENCE_ROOT.is_symlink(),
                       "evidence-already-exists")
        reserved_evidence = True
        handoff = bundle.unseal(archive, key_path, restored)
        validate_handoff(restored, handoff, inputs, source)
        record = bundle.read_file(bundle.EVIDENCE_ROOT / bundle.RECORD_NAME, bundle.MAX_RECORD,
                                  private=True)
        evidence = bundle.evidence_files(record, {
            role: bundle.read_file(bundle.EVIDENCE_ROOT / name, bundle.MAX_REPORT, private=True)
            for role, name in bundle.report_names(json.loads(record)).items()})
        journal = quiet_journal(app, restored, status_path)
        journal.value["authorization"] = {"reviewed_plan_sha256": inputs["reviewed_plan_sha256"],
                                          "prepare_run_id": inputs["prepare_run_id"],
                                          "prepare_run_attempt": inputs["prepare_run_attempt"]}
        journal.save()
        execute(app, operator, restored, inputs["reviewed_plan_sha256"], journal)
        success = True
    except Exception as error:
        if journal is not None:
            journal.finish(False)
            prepare.diagnostics.record_failure(app, error, root.resolve(), journal, env)
    finally:
        try:
            if journal is not None and evidence is not None:
                handoff["publication"] = {
                    "driver_sha": env["GITHUB_SHA"], "run_id": env["GITHUB_RUN_ID"],
                    "run_attempt": env["GITHUB_RUN_ATTEMPT"], "succeeded": success}
                app.write_json(restored / "handoff.json", handoff)
                try:
                    # Prepared bytes are unchanged; fresh build/caches/logs are excluded.
                    bundle.seal(restored, evidence, key, output, success=True, publication=True)
                    archive_ready = True
                except Exception:
                    success = False
        finally:
            try:
                with Path(env["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
                    stream.write("archive_ready=" + str(archive_ready).lower() + "\n")
            finally:
                cleanup_ok = True
                if reserved_evidence and bundle.EVIDENCE_ROOT.exists():
                    try:
                        shutil.rmtree(bundle.EVIDENCE_ROOT)
                    except Exception:
                        cleanup_ok = False
                if created_store:
                    try:
                        prepare.cleanup_store(store, env)
                    except Exception:
                        cleanup_ok = False
                status = json.loads(status_path.read_text())
                status.update(archive_ready=archive_ready,
                              cleanup="COMPLETE" if cleanup_ok else "FAILED")
                if not success or not archive_ready or not cleanup_ok:
                    status["status"] = "BLOCKED"
                prepare.public_status(status_path, status)
    return 0 if success and archive_ready and cleanup_ok else 1


def report() -> None:
    _, _, status_path = prepare.locations(dict(os.environ))
    status = (json.loads(status_path.read_text()) if status_path.is_file()
              else {"status": "NOT_STARTED"})
    status["archive_upload"] = os.environ.get("ARCHIVE_UPLOAD_OUTCOME", "unknown")
    if status.get("status") == "PUBLISHED" and status["archive_upload"] != "success":
        status.update(status="BLOCKED", stage="archive-upload")
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
        sys.exit("Schema431 publish BLOCKED; use bounded status and private recovery record")
