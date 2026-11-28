"""Main-only migration evidence, reviewed prepare and explicitly approved publish.

No operation in this module is invoked by a PR. Publication reuses app_release;
Firestore reviews and encrypted transport do not replace any of its gates.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")]

from scripts.static_ops import app_release as app  # noqa: E402
from scripts.static_ops import (  # noqa: E402  # noqa: E402
    migration_archive,
    migration_evidence,
    migration_review,
    release_automation,
    source_ci,
)
from scripts.static_ops import schema260_bundle as transport  # noqa: E402
from scripts.static_ops import schema260_diagnostics as diagnostics  # noqa: E402
from scripts.static_ops.schema260_prepare import refreshed_rules_token  # noqa: E402

JOBS = {
    "evidence-migration": "migration-evidence",
    "prepare-migration": "migration-prepare",
    "publish-migration": "migration-publish",
    "revoke-migration": "migration-revoke",
    "cleanup-migration": "migration-cleanup",
    "acceptance-migration": "migration-acceptance",
}


def scope(env, event):
    operation = (
        "evidence-migration"
        if env.get("GITHUB_EVENT_NAME") == "workflow_run"
        else "cleanup-migration" if env.get("GITHUB_EVENT_NAME") == "schedule"
        else event.get("inputs", {}).get("operation")
    )
    app.require(
        operation in JOBS
        and env.get("GITHUB_JOB") == JOBS[operation]
        and env.get("GITHUB_ACTIONS") == "true"
        and env.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and env.get("GITHUB_REPOSITORY") == app.REPO
        and env.get("GITHUB_REPOSITORY_ID") == "1314030412"
        and env.get("GITHUB_REPOSITORY_OWNER_ID") == "65487096"
        and env.get("GITHUB_EVENT_NAME") in ("workflow_dispatch", "workflow_run", "schedule")
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_WORKFLOW_REF")
        == app.REPO + "/.github/workflows/static-app-release.yml@refs/heads/main"
        and env.get("GITHUB_WORKFLOW_SHA") == env.get("GITHUB_SHA")
        and env.get("GITHUB_RUN_ATTEMPT") == "1"
        and re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", ""))
        and re.fullmatch(r"[1-9]\d{0,19}", env.get("GITHUB_RUN_ID", ""))
        and event.get("repository", {}).get("id") == 1314030412,
        "Fresh main migration dispatch required; reruns need new evidence and approval",
    )
    return operation


class MigrationOperator(app.Operator):
    pause_allowed = False
    publication_allowed = False
    resume_allowed = False

    def __init__(self, root=ROOT, **kwargs):
        super().__init__(root, **kwargs)
        self.run_id = self.env.get("GITHUB_RUN_ID", "")
        self.binding = None
        self.approval_check = None

    def idle(self):
        release_automation.ActionsOperator.idle(self)
        run = self.gh("actions/runs/" + self.run_id)
        app.require(
            run.get("event") == "workflow_dispatch"
            and run.get("head_branch") == "main"
            and run.get("head_sha") == self.env["GITHUB_SHA"]
            and run.get("run_attempt") == 1
            and run.get("repository", {}).get("id") == 1314030412,
            "Migration lease identity changed",
        )

    def gh(self, endpoint, method="GET", body=None):
        allowed = method == "GET"
        if self.pause_allowed or self.publication_allowed:
            allowed |= (
                method == "PATCH"
                and endpoint == "actions/variables/STATIC_AUTOMATION_ENABLED"
                and body == {"name": "STATIC_AUTOMATION_ENABLED", "value": "false"}
            )
        if self.publication_allowed:
            allowed |= (
                method == "PUT"
                and body is None
                and endpoint
                in (
                    "actions/workflows/" + app.WORKFLOW + "/enable",
                    "actions/workflows/" + app.WORKFLOW + "/disable",
                )
            )
            allowed |= (
                method == "PATCH"
                and endpoint == "actions/variables/STATIC_APPROVED_SHA"
                and body == {"name": "STATIC_APPROVED_SHA", "value": self.binding["sha"]}
            )
        if self.resume_allowed:
            allowed |= (
                method == "PATCH"
                and endpoint == "actions/variables/STATIC_AUTOMATION_ENABLED"
                and body == {"name": "STATIC_AUTOMATION_ENABLED", "value": "true"}
            )
        app.require(allowed, "Mutation is outside the approved migration phase")
        return super().gh(endpoint, method, body)

    def rules_get(self, path):
        self.env["STATIC_GOOGLE_ACCESS_TOKEN"] = refreshed_rules_token(
            self.env["STATIC_GOOGLE_CREDENTIALS_FILE"]
        )
        try:
            return super().rules_get(path)
        finally:
            self.env.pop("STATIC_GOOGLE_ACCESS_TOKEN", None)

    def snapshot(self, sha, current, *, paused=False):
        app.require(callable(self.approval_check), "Live review validation required")
        self.approval_check()
        app.require(
            self.binding is not None
            and sha == self.binding["sha"]
            and current == self.binding["current_sha"]
            and self.git("rev-parse", "HEAD") == self.binding["tooling_sha"],
            "Approved migration source or tooling changed",
        )
        source_ci.require_success(self.gh, sha)
        return super().snapshot(sha, current, paused=paused)

    def build(self, sha, snapshot, destination):
        info = destination.parent.lstat()
        app.require(
            stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
            "Private build parent required",
        )
        previous = os.umask(0o022)
        try:
            return super().build(sha, snapshot, destination)
        finally:
            os.umask(previous)

    def upload(self, destination, sha, upload_env):
        app.require(
            self.publication_allowed and sha == self.binding["sha"],
            "Explicit publication approval required",
        )
        app.require(callable(self.approval_check), "Live publication approval required")
        self.approval_check()
        return super().upload(destination, sha, upload_env)


def before_pause(operator):
    class Reader(MigrationOperator):
        def compatibility(self, sha, current, variables):
            value = operator.compatibility(sha, current, variables)
            self.schema_receipt, self.rules_receipt = (
                operator.schema_receipt,
                operator.rules_receipt,
            )
            return value

    reader = Reader(operator.root)
    reader.env, reader.binding = operator.env, operator.binding
    reader.approval_check = operator.approval_check
    return reader.snapshot(operator.binding["sha"], operator.binding["current_sha"])


def release_candidate(operator, sha, current):
    """Reject rollback/tag collisions before any pause or production mutation."""
    import publish_github_release as publisher

    branch = operator.source_branch(sha)
    operator.git("fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    operator.git("merge-base", "--is-ancestor", sha, "origin/" + branch)
    version = operator.git("show", sha + ":VERSION")
    publisher.release_line("refs/heads/" + branch, version)
    app.require(
        release_automation.disposition(version, sha, app.release(app.gate.ORIGIN, current), current)
        == "PUBLISH",
        "Migration candidate must be newer than the approved application",
    )
    tag = "v" + version
    publisher.check_release_collisions(app.REPO, tag)
    existing = publisher.tag_commit(app.REPO, tag)
    app.require(existing in (None, sha), "Existing tag identifies another application")
    selected = publisher.api(f"repos/{app.REPO}/releases/tags/{tag}")
    if selected is not None:
        release_automation.stable(selected)
        app.require(existing == sha, "Existing Release has no matching immutable tag")


def prepare(operator, evidence, reviewer, store, evidence_directory, journal):
    record = migration_review.attest(evidence, reviewer, evidence_directory)
    operator.schema_transition = evidence_directory / "SCHEMA_RECORD.json"
    operator.binding = record
    release_candidate(operator, record["sha"], record["current_sha"])
    # Real review is already recorded, but all compatibility/live gates still run
    # before stopping weather publication.
    initial = before_pause(operator)
    journal.value["automation_before"] = initial["variables"]["STATIC_AUTOMATION_ENABLED"]
    journal.save()
    operator.approval_check()
    operator.pause_allowed = True
    try:
        journal.mutation(
            "automation", lambda: operator.set_variable("STATIC_AUTOMATION_ENABLED", "false")
        )
    finally:
        operator.pause_allowed = False
    app.unchanged(
        initial,
        operator.snapshot(record["sha"], record["current_sha"]),
        paused=True,
        deployment=True,
    )
    plan = app.prepare(operator, record["sha"], record["current_sha"], store, journal)
    handoff = {
        "sha": record["sha"],
        "current_sha": record["current_sha"],
        "tooling_sha": record["tooling_sha"],
        "origin_run": app.release_review.identity(dict(os.environ)),
        "automation_before": initial["variables"]["STATIC_AUTOMATION_ENABLED"],
        "prepared": True,
        "plan_sha256": app.digest((store / "plan.json").read_bytes()),
    }
    app.write_json(store / "handoff.json", handoff)
    return plan, handoff


def github_release(operator, sha, store, token):
    import publish_github_release as publisher

    app.require(token, "GitHub Release publication authentication unavailable")
    previous_directory, previous_token = Path.cwd(), os.environ.get("GH_TOKEN")
    try:
        # The build checkout is writable by candidate code. Read release sources
        # from the approved commit in a separate checkout that never runs a build.
        with tempfile.TemporaryDirectory(prefix="navmate-release-metadata-") as directory:
            checkout = Path(directory) / "app"
            app.command([
                "git", "clone", "--no-hardlinks", "--no-checkout",
                str(operator.root), str(checkout),
            ])
            app.command(["git", "checkout", "--detach", sha], cwd=checkout)
            os.chdir(checkout)
            os.environ["GH_TOKEN"] = token
            # Execute trusted tooling, never the candidate's publisher script.
            publisher.publish(checkout, "refs/heads/" + operator.source_branch(sha), sha, app.REPO)
            os.chdir(previous_directory)
    finally:
        os.chdir(previous_directory)
        if previous_token is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = previous_token
    selected = release_automation.stable(
        operator.gh("releases/tags/v" + operator.git("show", sha + ":VERSION"))
    )
    app.require(
        release_automation.candidate(operator, selected) == sha,
        "Published Release identity mismatch",
    )


def publish(operator, approved, store, journal, release_token):
    plan, handoff = approved["plan"], approved["handoff"]
    operator.binding = plan["snapshot"]["schema_receipt"]["record"]
    operator.schema_transition = store.parent / "evidence/SCHEMA_RECORD.json"
    app.require(release_token, "GitHub Release publication authentication unavailable")
    release_candidate(operator, plan["sha"], plan["current_sha"])
    operator.publication_allowed = True
    app.publish(operator, plan["sha"], plan["current_sha"], store, approved["plan_sha256"], journal)
    # Migration prepare stopped automation, so app.publish deliberately leaves it
    # false. A Release failure or any uncertain readback must keep it that way.
    journal.value["github_release"] = "UNKNOWN"
    journal.save()
    operator.approval_check()
    github_release(operator, plan["sha"], store, release_token)
    journal.value["github_release"] = "CONFIRMED"
    journal.save()
    expected = {**plan["snapshot"]["variables"], "STATIC_APPROVED_SHA": plan["sha"]}
    app.require(
        operator.variables() == expected and operator.workflow()["state"] == "active",
        "Publication state changed before weather resume",
    )
    operator.verify(store / "fresh", plan["sha"], plan["snapshot"])
    app.require(
        operator.compatibility(plan["sha"], plan["current_sha"], expected)
        == plan["snapshot"]["rules_digest"],
        "Rules or evidence changed before resume",
    )
    operator.idle()
    operator.approval_check()
    app.require(handoff["automation_before"] in ("true", "false"), "Unknown prior weather state")
    if handoff["automation_before"] == "true":
        operator.resume_allowed = True
        try:
            journal.mutation(
                "automation", lambda: operator.set_variable("STATIC_AUTOMATION_ENABLED", "true")
            )
        finally:
            operator.resume_allowed = False
        expected["STATIC_AUTOMATION_ENABLED"] = "true"
    app.require(operator.variables() == expected, "Final approved source or weather state mismatch")
    journal.value["final_automation"] = expected["STATIC_AUTOMATION_ENABLED"]
    journal.save()


def report(reference):
    # Only an access-controlled link and exact digest. No private report fields.
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
        output.write(
            f"Review details in [Firestore Console]({reference['url']})\n\n"
            f"- Record ID: `{reference['id']}`\n"
            f"- SHA-256: `{reference['sha256']}`\n"
        )


def synthetic_acceptance(reviews):
    """No source receipt or signature: these records can never authorize publication."""
    sample = json.dumps({"synthetic_only": True, "saved": {"id": "synthetic-project"},
                         "latest": {"draft": "Synthetic sample for console inspection"}},
                        ensure_ascii=False, indent=2)
    evidence = {
        "schema_version": 1, "phase": "evidence", "synthetic_only": True,
        "created_at": datetime.now(UTC).isoformat(),
        "checks": {"old_to_new": {"observations": {"sample_sha256": app.digest(sample.encode())}}},
        "publication_authorized": False,
    }
    parent = reviews.save(evidence, sample_json=sample)
    # The lifecycle itself is exercised without pausing weather, building or publishing.
    reviews.begin(parent["id"], parent["sha256"], "prepare")
    plan = {"prepared_at": datetime.now(UTC).isoformat(), "synthetic_only": True,
            "changes": {"production": "NO_OPERATION"}, "candidate": "synthetic-candidate"}
    raw = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    prepared = reviews.save({
        "schema_version": 1, "phase": "prepared", "synthetic_only": True,
        "created_at": datetime.now(UTC).isoformat(), "plan": plan,
        "plan_sha256": app.digest(raw.encode()), "publication_authorized": False,
        "evidence_reference": {name: parent[name] for name in ("id", "sha256")},
    }, root=parent["id"], plan_json=raw)
    reviews.read(prepared["id"], prepared["sha256"], comment=True)
    return parent, prepared


def main():
    previous = os.umask(0o077)
    journal, reviews, reference = None, None, None
    evidence_root = None
    operation = "startup"
    owned_directories = []
    try:
        env = dict(os.environ)
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text())
        operation = scope(env, event)
        inputs = event.get("inputs", {})
        reader = app.Operator()
        reviews = migration_review.Reviews(
            reader, allow_disabled=operation in ("revoke-migration", "acceptance-migration"))
        key_text = os.environ.pop("STATIC_MIGRATION_ARCHIVE_KEY", "")
        # Capture evidence credentials before creating operators or candidate environments.
        os.environ.pop("STATIC_MIGRATION_EVIDENCE_CREDENTIALS_FILE", None)
        release_token = os.environ.pop("RELEASE_GITHUB_TOKEN", "")
        if operation == "cleanup-migration":
            reviews.cleanup()
            return 0
        if operation == "acceptance-migration":
            migration_review.approved_actor(reader, env)
            references = synthetic_acceptance(reviews)
            reviews.db.verify_isolation()
            for reference in references:
                report(reference)
            return 0
        if operation == "revoke-migration":
            actor = migration_review.approved_actor(reader, env)
            reference = reviews.revoke(inputs.get("migration_record_id", ""),
                                       inputs.get("reviewed_record_sha256", ""), actor)
            report(reference)
            return 0
        key = transport.key_bytes(key_text)
        operator = MigrationOperator()
        app.require(
            operator.git("rev-parse", "HEAD") == env["GITHUB_SHA"]
            and not operator.git("status", "--porcelain", "--untracked-files=all"),
            "Clean exact main tooling required",
        )
        temporary = Path(env["RUNNER_TEMP"]) / ("migration-" + env["GITHUB_RUN_ID"])
        temporary.mkdir(mode=0o700)
        owned_directories.append(temporary)
        if operation == "evidence-migration":
            sha = inputs.get("candidate_sha") or env["GITHUB_SHA"]
            if env["GITHUB_EVENT_NAME"] == "workflow_run":
                run = reader.gh("actions/runs/" + str(event["workflow_run"]["id"]))
                app.require(
                    run.get("status") == "completed"
                    and run.get("conclusion") == "success"
                    and run.get("event") == "push"
                    and run.get("path") == release_automation.PUBLISHER
                    and run.get("head_branch") in ("main", "release/1.x", "release/2.x")
                    and run.get("head_repository", {}).get("id") == 1314030412,
                    "Trusted release-preparation event required",
                )
                sha = run["head_sha"]
            collected = migration_evidence.collect(operator, sha, temporary)
            sample_json = collected.pop("sample_json")
            evidence = migration_review.signed_evidence(collected, key)
            reference = reviews.save(evidence, sample_json=sample_json)
            report(reference)
            return 0
        reviewer = migration_review.approved_actor(reader, env)
        number, expected = (
            inputs.get("migration_record_id", ""),
            inputs.get("reviewed_record_sha256", ""),
        )
        approved = reviews.begin(number, expected,
                                 "prepare" if operation == "prepare-migration" else "publish")
        evidence_root = number if operation == "prepare-migration" else approved[
            "evidence_reference"]["id"]
        root = Path("/tmp") / ("navmate-migration-" + evidence_root)
        root.mkdir(mode=0o700)  # Fixed paths preserve the reviewed receipt across runners.
        owned_directories.append(root)
        store, evidence_directory = root / "store", root / "evidence"
        if operation == "prepare-migration":
            migration_review.verify_evidence(approved, key)
            migration_archive.evidence_run(operator, approved)

            def recheck_evidence():
                current_review = reviews.read(number, expected)
                migration_review.verify_evidence(current_review, key)
                migration_archive.evidence_run(operator, current_review)

            operator.approval_check = recheck_evidence
            store.mkdir(mode=0o700)
            evidence_directory.mkdir(mode=0o700)
            sha = approved["identity"]["sha"]
            journal = app.Journal(store / "prepare-status.json", "prepare", sha)
            plan, handoff = prepare(
                operator, approved, reviewer, store, evidence_directory, journal
            )
            journal.finish(True)
            archive = Path(env["RUNNER_TEMP"]) / (
                "migration-result-" + env["GITHUB_RUN_ID"] + "-1.aesgcm"
            )
            files = {path.name: path.read_bytes() for path in evidence_directory.iterdir()}
            archive_digest = transport.seal(store, files, key, archive, success=True)
            reference = reviews.save(
                {
                    "schema_version": 1,
                    "phase": "prepared",
                    "candidate_sha": sha,
                    "created_at": datetime.now(UTC).isoformat(),
                    "plan": plan,
                    "handoff": handoff,
                    "plan_sha256": handoff["plan_sha256"],
                    "archive_sha256": archive_digest,
                    "reviewer": reviewer,
                    "evidence_reference": {"id": number, "sha256": expected},
                    "publication_authorized": False,
                },
                root=evidence_root,
                plan_json=(store / "plan.json").read_text(),
            )
        else:
            app.require(
                approved.get("phase") == "prepared"
                and approved.get("publication_authorized") is False,
                "Explicit prepared-plan review required",
            )
            archive = migration_archive.download(operator, approved, temporary)
            migration_archive.restore(archive, key, store, evidence_directory, approved)
            # Evidence edits/withdrawal after prepare invalidate publication.
            evidence_ref = approved["evidence_reference"]
            evidence = reviews.read(evidence_ref["id"], evidence_ref["sha256"])
            migration_review.verify_evidence(evidence, key)
            migration_archive.evidence_run(operator, evidence)

            def recheck_publication():
                current_review = reviews.read(number, expected, comment=True)
                migration_archive.source_run(operator, current_review)
                current_evidence = reviews.read(evidence_ref["id"], evidence_ref["sha256"])
                migration_review.verify_evidence(current_evidence, key)
                migration_archive.evidence_run(operator, current_evidence)

            operator.approval_check = recheck_publication
            journal = app.Journal(
                store / "publish-status.json", "publish", approved["candidate_sha"]
            )
            journal.value["authorization"] = {
                "reviewed_by": reviewer,
                "private_record_sha256": expected,
            }
            publish(operator, approved, store, journal, release_token)
            journal.finish(True)
            reference = reviews.save(
                {
                    "schema_version": 1,
                    "phase": "published",
                    "candidate_sha": approved["candidate_sha"],
                    "created_at": datetime.now(UTC).isoformat(),
                    "result": journal.value,
                    "reviewed_record_sha256": expected,
                    "evidence_reference": approved["evidence_reference"],
                    "prepared_reference": {"id": number, "sha256": expected},
                    "final_verified": True,
                },
                root=evidence_root,
            )
    except BaseException as error:
        if journal is not None:
            diagnostics.record_failure(app, error, ROOT, journal, dict(os.environ))
            try:
                journal.finish(
                    False, interrupted=isinstance(error, (KeyboardInterrupt, SystemExit))
                )
            except Exception:
                pass
            try:
                reference = reviews.save(
                    {
                        "schema_version": 1,
                        "phase": "blocked",
                        "candidate_sha": journal.value["sha"],
                        "created_at": datetime.now(UTC).isoformat(),
                        "result": journal.value,
                    },
                    root=evidence_root,
                )
                report(reference)
            except Exception:
                # No plaintext fallback to public artifacts/logs.
                pass
            # Journal changes/configuration and exception text stay in IAM-protected storage.
        elif reviews is not None:
            try:
                reference = reviews.save(
                    {
                        "schema_version": 1,
                        "phase": "blocked",
                        "candidate_sha": os.environ.get("GITHUB_SHA", "unknown"),
                        "created_at": datetime.now(UTC).isoformat(),
                        "result": {
                            "stage": operation,
                            "exception": type(error).__name__,
                            "reason": str(error)
                            if isinstance(error, app.Blocked)
                            else "Inspect the selected operation and its inputs",
                        },
                    },
                    root=evidence_root,
                )
                report(reference)
            except Exception:
                pass
        # Provider output, raw configuration and record bodies never enter public logs.
        print(
            "Migration BLOCKED. Inspect the Firestore record and production state before recovery; "
            "do not resume or retry an uncertain write."
        )
        return 1
    else:
        # The record is durably saved and read back. Notification cannot undo it.
        try:
            report(reference)
        except BaseException:
            print("Migration record saved. Summary unavailable; inspect the record in Firestore.")
            return 1
        return 0
    finally:
        cleanup_failed = False
        for directory in reversed(owned_directories):
            try:
                info = directory.lstat()
                app.require(
                    stat.S_ISDIR(info.st_mode)
                    and info.st_uid == os.getuid()
                    and info.st_mode & 0o077 == 0,
                    "Private cleanup scope changed",
                )
                try:
                    shutil.rmtree(directory)
                except PermissionError:
                    app.command(
                        ["sudo", "-n", "rm", "-rf", "--", str(directory)],
                        cwd=Path("/"),
                        env={"PATH": os.defpath},
                        timeout=120,
                    )
            except Exception:
                cleanup_failed = True
                print(
                    "Private runner cleanup incomplete; retain failure state and inspect the run."
                )
        os.umask(previous)
        if cleanup_failed:
            raise SystemExit("Migration cleanup failed; publication is not authorized by this run")


if __name__ == "__main__":
    raise SystemExit(main())
