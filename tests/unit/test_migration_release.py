"""Fail-closed GitHub migration review, transport and publication boundaries."""

import copy
import io
import json
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import yaml
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts.static_ops import app_release as app
from scripts.static_ops import migration_archive as archive
from scripts.static_ops import migration_evidence as evidence_tools
from scripts.static_ops import migration_release as migration
from scripts.static_ops import migration_review as review
from scripts.static_ops import schema260_bundle as transport

SHA, OLD, KEY = "a" * 40, "b" * 40, b"k" * 32


def evidence():
    return {
        "schema_version": 1,
        "phase": "evidence",
        "result": "PASS",
        "publication_authorized": False,
        "candidate_sha": SHA,
        "created_at": datetime.now(UTC).isoformat(),
        "identity": {"sha": SHA, "current_sha": OLD, "tooling_sha": SHA},
        "checks": {
            role: {
                "result": "PASS",
                "summary": "Measured synthetic evidence",
                "observations": {"receipt": 1},
            }
            for role in ("old_to_new", "old_writer_fenced", "storage_sync_roundtrip")
        },
    }


def test_modified_observations_cannot_be_resigned_by_digest_or_review():
    value = review.signed_evidence(evidence(), KEY)
    value["checks"]["old_to_new"]["observations"]["receipt"] = 2
    with pytest.raises(app.Blocked, match="sealed"):
        review.verify_evidence(value, KEY)



@pytest.mark.parametrize("tampered", [False, True])
def test_release_metadata_comes_from_approved_commit_not_build_checkout(
    tmp_path, monkeypatch, tampered,
):
    import subprocess
    from pathlib import Path

    import publish_github_release as publisher

    root = tmp_path / "trusted"
    root.mkdir()
    notes = "### 利用者向け\n\n#### 修正\n\n- Approved\n\n### 開発者向け\n\n- Tests\n"
    (root / "VERSION").write_text("2.6.0\n")
    (root / "CHANGELOG.md").write_text("# Changes\n\n## 2.6.0\n\n" + notes)

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    git("init", "--quiet")
    git("add", "VERSION", "CHANGELOG.md")
    git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "source")
    sha = git("rev-parse", "HEAD")
    store = tmp_path / "store"
    build = store / "fresh/app"
    build.mkdir(parents=True)
    for name in ("VERSION", "CHANGELOG.md"):
        text = (root / name).read_text()
        (build / name).write_text(text.replace("2.6.0", "2.6.1").replace("Approved", "Changed")
                                  if tampered else text)
    calls = []
    original_run = publisher.run

    def run(*args):
        if args[0] == "git":
            return original_run(*args)
        calls.append((args, Path(args[args.index("--notes-file") + 1]).read_text()))
        return ""

    monkeypatch.setattr(publisher, "run", run)
    monkeypatch.setattr(publisher, "api", lambda path: [] if "?per_page=" in path else None)
    monkeypatch.setattr(migration.release_automation, "stable", lambda value: value)
    monkeypatch.setattr(migration.release_automation, "candidate", lambda *_: sha)
    operator = SimpleNamespace(root=root, source_branch=lambda _: "main", git=git, gh=lambda _: {})
    migration.github_release(operator, sha, store, "test-only")
    assert len(calls) == 1
    argv, published_notes = calls[0]
    assert argv[:4] == ("gh", "release", "create", "v2.6.0")
    assert argv[argv.index("--target") + 1] == sha
    assert published_notes == notes


@pytest.mark.parametrize(
    "actor,permission,kind",
    [("app[bot]", "admin", "Bot"), ("viewer", "read", "User"), ("bot", "write", "Bot")],
)
def test_only_authorized_human_dispatch_can_attest(actor, permission, kind):
    operator = SimpleNamespace(
        gh=lambda _: {"permission": permission, "user": {"login": actor, "type": kind}}
    )
    with pytest.raises(app.Blocked):
        review.approved_actor(operator, {"GITHUB_ACTOR": actor})


def test_failed_check_cannot_be_turned_into_reviewed_pass(tmp_path):
    value = evidence()
    value["checks"]["old_to_new"]["result"] = "FAIL"
    with pytest.raises(app.Blocked):
        review.attest(value, "human", tmp_path)
    assert not (tmp_path / "SCHEMA_RECORD.json").exists()


def test_real_human_attestation_retains_exact_observations(tmp_path):
    value = evidence()
    record = review.attest(value, "human", tmp_path)
    for role, check in record["checks"].items():
        content = (tmp_path / check["record"]["path"]).read_bytes()
        assert app.digest(content) == check["record"]["sha256"]
        assert json.loads(content)["observations"] == value["checks"][role]["observations"]
        assert check["reviewed_by"] == "human"


def seal_files(tmp_path, files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, content in files:
            zipped.writestr(name, content)
    nonce = b"n" * 12
    raw = transport.MAGIC + nonce + AESGCM(KEY).encrypt(nonce, output.getvalue(), transport.MAGIC)
    path = tmp_path / "archive"
    path.write_bytes(raw)
    return path, app.digest(raw)


def test_archive_restores_only_exact_approved_plan_and_private_files(tmp_path):
    plan, handoff = b'{"sha":"candidate"}', b'{"prepared":true}'
    path, digest = seal_files(
        tmp_path,
        [
            ("store/plan.json", plan),
            ("store/handoff.json", handoff),
            ("evidence/SCHEMA_RECORD.json", b"{}"),
        ],
    )
    approved = {
        "archive_sha256": digest,
        "plan_sha256": app.digest(plan),
        "plan": json.loads(plan),
        "handoff": json.loads(handoff),
    }
    archive.restore(path, KEY, tmp_path / "store", tmp_path / "evidence", approved)
    assert (tmp_path / "store/plan.json").read_bytes() == plan
    assert (tmp_path / "store/plan.json").stat().st_mode & 0o077 == 0
    with pytest.raises(app.Blocked, match="Fresh restore"):
        archive.restore(path, KEY, tmp_path / "store", tmp_path / "evidence", approved)


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/outside",
        "store/../outside",
        "store/secret",
        "store/prepared/upload/../../outside",
    ],
)
def test_archive_rejects_paths_before_creating_destination(tmp_path, name):
    path, digest = seal_files(tmp_path, [(name, b"bad")])
    with pytest.raises(app.Blocked):
        archive.restore(
            path, KEY, tmp_path / "store", tmp_path / "evidence", {"archive_sha256": digest}
        )
    assert not (tmp_path / "store").exists()


def test_archive_rejects_authenticated_but_unreviewed_plan(tmp_path):
    path, digest = seal_files(tmp_path, [("store/plan.json", b"{}")])
    with pytest.raises(app.Blocked, match="plan mismatch"):
        archive.restore(
            path,
            KEY,
            tmp_path / "store",
            tmp_path / "evidence",
            {"archive_sha256": digest, "plan_sha256": "0" * 64},
        )


@pytest.mark.parametrize("fault", [None, "rerun", "job", "workflow", "inactive", "repository"])
def test_source_receipt_requires_exact_completed_workflow_and_job(fault):
    run = {
        "id": 12,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": SHA,
        "path": ".github/workflows/static-app-release.yml",
        "workflow_id": 20,
        "repository": {"id": 1314030412},
        "head_repository": {"id": 1314030412},
    }
    workflow = {"path": run["path"], "id": 20, "state": "active"}
    job = {"id": 1, "name": "migration-prepare", "status": "completed", "conclusion": "success"}
    if fault == "rerun":
        run["run_attempt"] = 2
    elif fault == "job":
        job["conclusion"] = "skipped"
    elif fault == "workflow":
        run["workflow_id"] = 21
    elif fault == "inactive":
        workflow["state"] = "disabled_manually"
    elif fault == "repository":
        run["head_repository"]["id"] = 1
    operator = SimpleNamespace(
        gh=lambda path: (
            workflow
            if "workflows/" in path
            else {"total_count": 1, "jobs": [job]}
            if "jobs?" in path
            else run
        )
    )

    def verify():
        return archive.completed_run(
            operator,
            {"run_id": "12", "run_attempt": "1"},
            SHA,
            "migration-prepare",
            {"workflow_dispatch"},
        )

    if fault:
        with pytest.raises(app.Blocked):
            verify()
    else:
        assert verify() == run


@pytest.mark.parametrize("fault", ["skipped", "missing", "attempt"])
def test_browser_evidence_requires_executed_contracts_step(monkeypatch, fault):
    receipt = {"run_id": 12, "run_attempt": 1}
    step = {
        "name": "Verify real SDK, Rules and cross-device Local-first workflows",
        "status": "completed",
        "conclusion": "success",
    }
    job = {
        "id": 1,
        "name": "account-sync-tests (contracts, 1)",
        "status": "completed",
        "conclusion": "success",
        "steps": [step],
    }
    if fault == "skipped":
        step["conclusion"] = "skipped"
    elif fault == "missing":
        job["steps"] = []
    monkeypatch.setattr(
        evidence_tools.source_ci,
        "require_success",
        lambda *_: {**receipt, "run_attempt": 2} if fault == "attempt" else receipt,
    )
    operator = SimpleNamespace(
        git=lambda *_: SHA,
        source_digest=lambda *_: "same",
        gh=lambda _: {"total_count": 1, "jobs": [job]},
    )
    with pytest.raises(app.Blocked):
        evidence_tools.browser_ci(operator, SHA, receipt)


def test_publish_never_resumes_weather_after_release_creation_failure(monkeypatch, tmp_path):
    record = {"sha": SHA, "current_sha": OLD}
    snapshot = {"schema_receipt": {"record": record}, "variables": {}}
    approved = {
        "plan": {"sha": SHA, "current_sha": OLD, "snapshot": snapshot},
        "handoff": {"automation_before": "true"},
        "plan_sha256": "d" * 64,
    }
    operator = SimpleNamespace(resume_allowed=False, approval_check=lambda: None)
    monkeypatch.setattr(migration, "release_candidate", lambda *_: None)
    monkeypatch.setattr(app, "publish", lambda *_: None)
    monkeypatch.setattr(
        migration,
        "github_release",
        lambda *_: (_ for _ in ()).throw(app.Blocked("uncertain release creation")),
    )
    journal = app.Journal(tmp_path / "status.json", "publish", SHA)
    with pytest.raises(app.Blocked, match="uncertain"):
        migration.publish(operator, approved, tmp_path, journal, "test-only")
    assert journal.value["github_release"] == "UNKNOWN"
    assert operator.resume_allowed is False


def test_workflow_routing_cannot_publish_without_manual_selection():
    workflow = (app.ROOT / ".github/workflows/static-app-release.yml").read_text()
    jobs = yaml.safe_load(workflow)["jobs"]
    for phase in ("prepare", "publish"):
        job = jobs["migration-" + phase]
        assert " ".join(job["if"].split()) == (
            "github.repository == 'Yuto-24/NavMate' && "
            "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' && "
            f"inputs.operation == '{phase}-migration'"
        )
        assert job["concurrency"] == {
            "group": "static-production", "cancel-in-progress": False, "queue": "max",
        }
    publisher = (app.ROOT / ".github/workflows/publish-github-release.yml").read_text()
    assert "needs.preflight.outputs.route == 'AUTOMATIC'" in publisher
    preflight = (app.ROOT / ".github/workflows/release-preflight.yml").read_text()
    assert "secrets." not in preflight and "environment:" not in preflight


@pytest.mark.parametrize("path", ["web/package.json", "web/e2e", "firebase.json"])
def test_changed_evidence_commands_or_fixtures_stop_before_ci_receipt(path):
    operator = SimpleNamespace(
        git=lambda *_: OLD,
        source_digest=lambda sha, name: "changed" if sha == SHA and name == path else "same",
        gh=lambda _: pytest.fail("Changed test definition must stop before CI reads"),
    )
    with pytest.raises(app.Blocked, match="trusted evidence recipe"):
        evidence_tools.browser_ci(operator, SHA, {"run_id": 12, "run_attempt": 1})


def test_withdrawn_approval_stops_release_creation_after_app_readback(monkeypatch, tmp_path):
    approved = {
        "plan": {"sha": SHA, "current_sha": OLD, "snapshot": {"schema_receipt": {"record": {}}}},
        "handoff": {},
        "plan_sha256": "d" * 64,
    }
    operator = SimpleNamespace(
        approval_check=lambda: (_ for _ in ()).throw(app.Blocked("review withdrawn"))
    )
    monkeypatch.setattr(migration, "release_candidate", lambda *_: None)
    monkeypatch.setattr(app, "publish", lambda *_: None)
    monkeypatch.setattr(
        migration,
        "github_release",
        lambda *_: pytest.fail("Withdrawn review must stop Release creation"),
    )
    journal = app.Journal(tmp_path / "status.json", "publish", SHA)
    with pytest.raises(app.Blocked, match="review withdrawn"):
        migration.publish(operator, approved, tmp_path, journal, "test-only")


@pytest.mark.parametrize("automation", ["true", "false"])
@pytest.mark.parametrize(
    "failure",
    [None, "prepare-build", "fresh-build", "upload", "verify", "approve", "release", "resume"],
)
def test_migration_reuses_real_state_machine_and_retains_pause_on_failure(
    monkeypatch, tmp_path, automation, failure
):
    from tests.unit.test_static_app_release import NEW, OLD, SimulatedOperator

    operator = SimulatedOperator(tmp_path / "tooling", automation=automation)
    operator.approval_check = lambda: operator.event("review")
    operator.fail = failure
    value = evidence()
    value["identity"].update(sha=NEW, current_sha=OLD)
    original_attest = review.attest

    def attest(*args):
        record = original_attest(*args)
        operator.state["schema_receipt"] = {"record": record}
        return record

    monkeypatch.setattr(review, "attest", attest)
    monkeypatch.setattr(migration, "release_candidate", lambda *_: operator.event("candidate"))
    monkeypatch.setattr(migration, "before_pause", lambda *_: operator.snapshot(NEW, OLD))
    monkeypatch.setattr(migration, "github_release", lambda *_: operator.event("release"))
    store, directory = tmp_path / "store", tmp_path / "evidence"
    store.mkdir()
    directory.mkdir()
    journal = app.Journal(store / "prepare-status.json", "prepare", NEW)

    def execute():
        plan, handoff = migration.prepare(operator, value, "human", store, directory, journal)
        assert operator.state["variables"]["STATIC_AUTOMATION_ENABLED"] == "false"
        approved = {"plan": plan, "handoff": handoff, "plan_sha256": handoff["plan_sha256"]}
        publication = app.Journal(store / "publish-status.json", "publish", NEW)
        migration.publish(operator, approved, store, publication, "test-only")

    fails = failure is not None and not (failure == "resume" and automation == "false")
    if fails:
        with pytest.raises(app.Blocked):
            execute()
        assert operator.state["variables"]["STATIC_AUTOMATION_ENABLED"] == "false"
    else:
        execute()
        assert operator.state["variables"]["STATIC_APPROVED_SHA"] == NEW
        assert operator.state["variables"]["STATIC_AUTOMATION_ENABLED"] == automation
        assert operator.calls.index("fresh-build") < operator.calls.index("upload")
        assert operator.calls.index("approve") < operator.calls.index("release")
        if automation == "true":
            assert operator.calls.index("release") < operator.calls.index("resume")
    assert operator.calls.count("upload") <= 1
    assert "rollback" not in operator.calls


@pytest.mark.parametrize("failure", [None, "build", "timeout", "first-remove", "probe-and-remove"])
def test_probe_entrypoint_and_all_image_cleanup_attempts(monkeypatch, tmp_path, failure):
    import subprocess

    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    calls, present, removals = [], set(), []
    original_error = subprocess.TimeoutExpired("docker build", 1800) if failure == "timeout" else (
        app.Blocked("original build or probe failure")
    )

    def command(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "build"]:
            tag = argv[argv.index("--tag") + 1]
            if failure == "build":
                raise original_error
            present.add(tag)
            if failure == "timeout":
                raise original_error
        elif argv[:2] == ["docker", "run"]:
            assert argv[argv.index("--entrypoint") + 1] == "python"
            assert argv.count("python") == 1
            assert argv[argv.index("--env") + 1] == "PYTHONOPTIMIZE=0"
            if argv[-1] == "generate":
                return '{"synthetic":true}'
            if failure == "probe-and-remove":
                raise original_error
            return '{"result":"PASS"}'
        elif argv[:3] == ["docker", "image", "ls"]:
            return "image-id" if argv[-1].removeprefix("reference=") in present else ""
        elif argv[:3] == ["docker", "image", "rm"]:
            removals.append(argv[-1])
            if len(removals) == 1 and failure in ("first-remove", "probe-and-remove"):
                raise app.Blocked("remove failed")
        return ""

    monkeypatch.setattr(app, "command", command)
    operator = SimpleNamespace(root=tmp_path)
    if failure:
        with pytest.raises((app.Blocked, subprocess.TimeoutExpired)) as error:
            evidence_tools.actual_versions(operator, SHA, OLD, tmp_path)
        if failure != "first-remove":
            assert error.value is original_error
    else:
        assert evidence_tools.actual_versions(operator, SHA, OLD, tmp_path)["result"] == "PASS"
    assert len(removals) == (0 if failure == "build" else 1 if failure == "timeout" else 2)


@pytest.mark.parametrize("change", [None, "wind", "altitude", "selected_forecast_model"])
def test_actual_version_probe_compares_every_restored_draft_field(monkeypatch, tmp_path, change):
    from scripts.static_ops import migration_probe as probe

    project = {"id": "synthetic", "pilot_name": "synthetic unsaved draft", "route_nodes": [],
               "wind": {"speed": 10}, "altitude": 5000, "selected_forecast_model": "MSM"}
    record = {"id": "synthetic", "draft": project,
              "lastCalculation": {"outcome": {}, "destination_wind": {}}}
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"app_version": "2.5.2", "saved": record, "latest": record}))
    (tmp_path / "VERSION").write_text("2.6.0")

    class Application:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

        def dispatch(self, action, value):
            if action == "validateRecord":
                return json.dumps(value)
            if action == "bootstrap":
                return "{}"
            recovery = copy.deepcopy(value["working"])
            if change:
                recovery["project"][change] = "silently changed"
            return json.dumps({"workingRecovery": recovery, "project": recovery["project"],
                               "readiness": {"calculationIsCurrent": False}})

    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "LocalApplication", Application)
    monkeypatch.setattr(probe, "migrate_record", lambda value: SimpleNamespace(
        model_dump=lambda **_: value
    ))
    if change:
        with pytest.raises(AssertionError):
            probe.verify(path)
    else:
        probe.verify(path)
