"""Publish only an explicitly approved #260 plan through the fixed reviewed tooling."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

if __package__:
    from . import schema260_bundle as bundle
    from . import schema260_prepare as prepare
else:
    import schema260_bundle as bundle
    import schema260_prepare as prepare

OPERATION = "publish-schema260"
PUBLISH_DEADLINE_SECONDS = 80 * 60


def scope(env: dict, event: dict) -> dict:
    prepare.scope(env, event, operation=OPERATION, job="manual-publish-v260")
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
        allow_readback_waiters = True

        def jobs_for(self, run_id, attempt):
            page, count, seen, jobs = 1, None, set(), []
            while True:
                value = self.gh(
                    f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}")
                rows, total = value["jobs"], value["total_count"]
                app.require(type(total) is int and total > 0 and isinstance(rows, list)
                            and (count is None or total == count), "Invalid job inventory")
                count = total
                for job in rows:
                    job_id = job.get("id")
                    app.require(type(job_id) is int and job_id > 0 and job_id not in seen
                                and job.get("run_id") == run_id
                                and ("run_attempt" not in job or job["run_attempt"] == attempt)
                                and ("head_sha" not in job or job["head_sha"] == env["GITHUB_SHA"]),
                                "Invalid job identity")
                    seen.add(job_id)
                    jobs.append(job)
                app.require(len(seen) <= total, "Invalid job inventory")
                if len(seen) == total:
                    return jobs
                app.require(len(rows) == 100, "Incomplete job inventory")
                page += 1

        def read_lease(self):
            output = app.command([
                "gh", "api", "--hostname", "github.com", "--method", "GET",
                "-H", "X-GitHub-Api-Version: 2026-03-10",
                "repos/" + prepare.REPO + "/actions/concurrency_groups/static-production",
            ], env={**{key: self.env[key] for key in ("PATH", "HOME", "GH_TOKEN")
                       if key in self.env}, "GH_PROMPT_DISABLED": "1"})
            return json.loads(output)

        def validate_readback_waiters(self, active, workflow_id):
            app.require(all(row.get("event") == "workflow_dispatch"
                            and row.get("display_title") == "schema260-readback" for row in active),
                        "Another publication run is not idle")
            own_id = int(env["GITHUB_RUN_ID"])
            own_jobs = self.jobs_for(own_id, int(env["GITHUB_RUN_ATTEMPT"]))
            own = [j for j in own_jobs if j.get("name") == "manual-publish-v260"]
            app.require(len(own) == 1 and own[0].get("status") == "in_progress"
                        and all(j is own[0] or j.get("status") == "completed" for j in own_jobs),
                        "Publication job identity unclear")
            lease = self.read_lease()
            members, count = lease.get("group_members"), lease.get("total_count")
            app.require(lease.get("group_name") == "static-production" and type(count) is int
                        and 1 <= count <= 100 and isinstance(members, list)
                        and len(members) == count,
                        "Unknown publication lease")
            pairs, waiters = set(), {}
            for member in members:
                run_id, job_id = member.get("run_id"), member.get("job_id")
                app.require(type(run_id) is int and run_id > 0 and type(job_id) is int
                            and job_id > 0 and (run_id, job_id) not in pairs,
                            "Unknown publication lease")
                pairs.add((run_id, job_id))
                if run_id == own_id:
                    app.require(job_id == own[0]["id"] and member.get("status") == "in_progress",
                                "Publication lock not held")
                else:
                    app.require(member.get("status") == "pending" and run_id not in waiters,
                                "Another publication holds the lock")
                    waiters[run_id] = job_id
            app.require((own_id, own[0]["id"]) in pairs, "Publication lock missing")
            active_ids = {row["id"] for row in active}
            app.require(active_ids <= waiters.keys(), "Another publication run is not idle")
            for run_id, job_id in waiters.items():
                run = self.gh(f"actions/runs/{run_id}")
                app.require(run.get("id") == run_id and run.get("workflow_id") == workflow_id
                            and run.get("path") == prepare.WORKFLOW
                            and run.get("event") == "workflow_dispatch"
                            and run.get("display_title") == "schema260-readback"
                            and run.get("head_branch") == "main"
                            and run.get("head_sha") == env["GITHUB_SHA"]
                            and run.get("status") in ("queued", "pending", "waiting",
                                                      "requested", "in_progress")
                            and run.get("repository", {}).get("id") == prepare.REPO_ID
                            and run.get("head_repository", {}).get("id") == prepare.REPO_ID
                            and type(run.get("run_attempt")) is int and run["run_attempt"] > 0,
                            "Readback waiter identity unclear")
                jobs = self.jobs_for(run_id, run["run_attempt"])
                match = [j for j in jobs if j.get("id") == job_id]
                app.require(len(match) == 1 and match[0].get("name") == "readback-v260"
                            and match[0].get("status") in ("queued", "pending")
                            and all(j is match[0] or j.get("status") == "completed" for j in jobs),
                            "Readback waiter job unclear")

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
            self.idle()
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
        and run.get("display_title") == "schema260-prepare"
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
    matches = [job for job in jobs if job.get("name") == "manual-prepare-v260"]
    bundle.require(len(matches) == 1 and matches[0].get("status") == "completed"
                   and matches[0].get("conclusion") == "success", "prepare-job-result")
    return run


def download(operator, inputs: dict, store: Path) -> tuple[Path, dict]:
    run = source_run(operator, inputs)
    run_id, attempt = inputs["prepare_run_id"], inputs["prepare_run_attempt"]
    name = f"schema260-{run_id}-{attempt}"
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
    expected = f"schema260-result-{run_id}-{attempt}.aesgcm"
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
            if hasattr(self, "end_stage"):
                self.end_stage(success)
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
    encoded_key = os.environ.pop("SCHEMA260_ARCHIVE_KEY", "")
    env = dict(os.environ)
    store, output, status_path = prepare.locations(env)
    prepare.public_status(status_path, {"status": "BLOCKED", "stage": "scope",
                                       "archive_ready": False})
    deadline = {"expired": False, "command_active": False}
    def expired(_signum, _frame):
        deadline["expired"] = True
        if not deadline["command_active"]:
            raise TimeoutError("publish deadline expired")
    previous_handler = signal.signal(signal.SIGALRM, expired)
    signal.alarm(PUBLISH_DEADLINE_SECONDS)
    app, original_command = None, None
    created_store, reserved_evidence = False, False
    success, archive_ready = False, False
    archive_errors = {}
    journal, evidence, handoff = None, None, None
    restored = store / "plan"
    transfer_timings = []
    try:
        inputs = scope(env, json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text()))
        prepare.checked_checkout(Path(__file__).resolve().parents[2], env["GITHUB_SHA"])
        bundle.require(all(env.get(name) for name in (
            "GH_TOKEN", "CLOUDFLARE_API_TOKEN", "STATIC_GOOGLE_ACCESS_TOKEN")), "credentials")
        bundle.require(all(shutil.which(name) for name in ("gh", "git", "docker", "node")),
                       "runner-tools")
        key = bundle.key_bytes(encoded_key)
        app = prepare.load_tooling(root)
        original_command = app.command
        def bounded_command(*args, **kwargs):
            if deadline["expired"]:
                raise TimeoutError("publish deadline expired")
            deadline["command_active"] = True
            try:
                result = original_command(*args, **kwargs)
            finally:
                deadline["command_active"] = False
            if deadline["expired"]:
                raise TimeoutError("publish deadline expired")
            return result
        app.command = bounded_command
        operator = publication_operator(app, root.resolve(), env)
        store.mkdir(mode=0o700, exist_ok=False)
        created_store = True
        def save_transfer():
            prepare.release_timing.write(store / "transfer-timings.json", transfer_timings)
        with prepare.release_timing.measure(transfer_timings, save_transfer, 'artifact-download'):
            archive, source = download(operator, inputs, store)
        key_path = store / "archive.key"
        bundle.write_private(key_path, encoded_key.encode("ascii"))
        bundle.require(not bundle.EVIDENCE_ROOT.exists() and not bundle.EVIDENCE_ROOT.is_symlink(),
                       "evidence-already-exists")
        reserved_evidence = True
        with prepare.release_timing.measure(transfer_timings, save_transfer, 'artifact-decrypt'):
            handoff = bundle.unseal(archive, key_path, restored)
        validate_handoff(restored, handoff, inputs, source)
        record = bundle.read_file(bundle.EVIDENCE_ROOT / bundle.RECORD_NAME, bundle.MAX_RECORD,
                                  private=True)
        evidence = bundle.evidence_files(record, {
            role: bundle.read_file(bundle.EVIDENCE_ROOT / name, bundle.MAX_REPORT, private=True)
            for role, name in bundle.report_names(json.loads(record)).items()})
        journal = quiet_journal(app, restored, status_path)
        journal.value.setdefault("timings", []).extend(transfer_timings)
        journal.value["authorization"] = {"reviewed_plan_sha256": inputs["reviewed_plan_sha256"],
                                          "prepare_run_id": inputs["prepare_run_id"],
                                          "prepare_run_attempt": inputs["prepare_run_attempt"]}
        journal.save()
        execute(app, operator, restored, inputs["reviewed_plan_sha256"], journal)
        success = True
    except Exception as error:
        signal.alarm(0)
        if app is not None and original_command is not None:
            app.command = original_command
        if journal is not None:
            journal.finish(False)
            prepare.diagnostics.record_failure(app, error, root.resolve(), journal, env)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        if app is not None and original_command is not None:
            app.command = original_command
        try:
            if journal is not None and evidence is not None:
                handoff["publication"] = {
                    "driver_sha": env["GITHUB_SHA"], "run_id": env["GITHUB_RUN_ID"],
                    "run_attempt": env["GITHUB_RUN_ATTEMPT"], "succeeded": success}
                try:
                    app.write_json(restored / "handoff.json", handoff)
                    # Prepared bytes are unchanged; fresh build/caches/logs are excluded.
                    timing_saved = prepare.encrypted_save(
                        restored, journal, evidence, key, output, success=True, publication=True)
                    archive_ready = True
                    bundle.require(timing_saved, "archive-timing-save")
                except Exception as error:
                    success = False
                    archive_errors.update(
                        stage="archive",
                        archive_error=prepare.diagnostics.archive_error_code(error))
                    prepare.diagnostics.record_failure(app, error, root.resolve(), journal, env,
                                                       entry="archive_failure")
                    for update in (lambda: journal.stage("archive"),
                                   lambda: journal.finish(False)):
                        try:
                            update()
                        except Exception as status_error:
                            prepare.diagnostics.record_failure(
                                app, status_error, root.resolve(), journal, env,
                                entry="archive_status_failure")
                    if not archive_ready:
                        # Keep the actual publication outcome and mutation journal,
                        # but never restore this reduced archive as a prepared plan.
                        handoff.update(prepared=False, plan_sha256=None, prepared_at=None)
                        try:
                            timing_saved = prepare.encrypted_save(
                                restored, journal, evidence, key, output,
                                success=False, publication=True,
                                handoff_override=json.dumps(handoff, sort_keys=True).encode())
                            archive_ready = True
                            bundle.require(timing_saved, "archive-timing-save")
                        except Exception as recovery_error:
                            archive_errors["archive_recovery_error"] = (
                                prepare.diagnostics.archive_error_code(recovery_error))
        finally:
            try:
                with Path(env["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
                    stream.write("archive_ready=" + str(archive_ready).lower() + "\n")
                    review_ready = prepare.review_result(
                        restored, journal, output, status_path, env, archive_ready,
                        mode="publish", transfer_timings=transfer_timings)
                    stream.write("review_ready=" + str(review_ready).lower() + "\n")
                    if not review_ready:
                        success = False
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
                status.update(archive_errors)
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
    status["publish_step"] = os.environ.get("PUBLISH_STEP_OUTCOME", "unknown")
    status["review_upload"] = os.environ.get("REVIEW_UPLOAD_OUTCOME", "unknown")
    status["archive_upload"] = os.environ.get("ARCHIVE_UPLOAD_OUTCOME", "unknown")
    if status.get("status") == "PUBLISHED" and (status["publish_step"] != "success"
                                               or status["archive_upload"] != "success"
                                               or status["review_upload"] != "success"):
        status.update(status="BLOCKED", stage=("publish-step" if status["publish_step"] != "success"
                                                else "archive-upload"))
    status["workflow_measurement"] = prepare.release_timing.workflow_report(dict(os.environ))
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
        sys.exit("Schema260 publish BLOCKED; use bounded status and private recovery record")
