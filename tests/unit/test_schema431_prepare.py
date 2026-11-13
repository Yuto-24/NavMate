"""No real provider calls: dispatch, evidence, pause ordering and private handoff."""

import base64
import copy
import gzip
import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts.static_ops import app_release as app
from scripts.static_ops import schema431_bundle as bundle
from scripts.static_ops import schema431_prepare as driver


@pytest.fixture
def context():
    env = {
        "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY": driver.REPO, "GITHUB_REPOSITORY_ID": str(driver.REPO_ID),
        "GITHUB_REPOSITORY_OWNER_ID": str(driver.OWNER_ID),
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": driver.REPO + "/" + driver.WORKFLOW + "@refs/heads/main",
        "GITHUB_SHA": "e" * 40, "GITHUB_WORKFLOW_SHA": "e" * 40,
        "GITHUB_JOB": "manual-prepare", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
    }
    repository = {"id": driver.REPO_ID, "full_name": driver.REPO,
                  "owner": {"id": driver.OWNER_ID}, "private": False}
    event = {"repository": repository,
             "inputs": {"operation": driver.OPERATION, "release_id": ""}}
    run = {"id": 123, "run_attempt": 2, "workflow_id": 456, "path": driver.WORKFLOW,
           "event": "workflow_dispatch", "status": "in_progress", "head_branch": "main",
           "head_sha": env["GITHUB_SHA"], "repository": repository,
           "head_repository": repository}
    return env, event, run


def test_scope_accepts_only_the_explicit_main_operation(context):
    env, event, _ = context
    driver.scope(env, event)


@pytest.mark.parametrize("field,value", [
    ("GITHUB_EVENT_NAME", "release"), ("GITHUB_EVENT_NAME", "workflow_run"),
    ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_WORKFLOW_REF", "Yuto-24/NavMate/other.yml@refs/heads/main"),
    ("GITHUB_WORKFLOW_SHA", "f" * 40), ("GITHUB_REPOSITORY_ID", "1"),
    ("GITHUB_REPOSITORY_OWNER_ID", "1"), ("GITHUB_JOB", "publish"),
    ("RUNNER_ENVIRONMENT", "self-hosted"), ("GITHUB_RUN_ATTEMPT", "../2"),
])
def test_wrong_dispatch_context_is_rejected(context, field, value):
    env, event, _ = context
    env[field] = value
    with pytest.raises(bundle.InvalidBundle):
        driver.scope(env, event)


@pytest.mark.parametrize("inputs", [None, {}, {"operation": "readback"},
    {"operation": "replay-release"}, {"operation": "prepare-schema431", "release_id": "1"}])
def test_modes_cannot_overlap(context, inputs):
    env, event, _ = context
    event["inputs"] = inputs or {}
    with pytest.raises(bundle.InvalidBundle):
        driver.scope(env, event)


@pytest.fixture
def idle_operator(tmp_path, monkeypatch, context):
    env, _, own = context
    op = driver.manual_operator(app, tmp_path, env)
    responses = {
        "actions/workflows/static-app-release.yml": {
            "path": driver.WORKFLOW, "state": "active", "id": 456},
        "actions/runs/123": own,
        "actions/workflows/static-production.yml/runs?per_page=100&page=1": {
            "total_count": 1, "workflow_runs": [{"id": 1, "status": "completed"}]},
        "actions/workflows/static-app-release.yml/runs?per_page=100&page=1": {
            "total_count": 1, "workflow_runs": [own]},
    }
    def gh(self, endpoint, method="GET", body=None):
        assert method == "GET"
        return copy.deepcopy(responses[endpoint])
    monkeypatch.setattr(app.Operator, "gh", gh)
    return op, responses


def test_own_in_progress_run_is_the_only_exception(idle_operator):
    op, _ = idle_operator
    op.idle()


@pytest.mark.parametrize("workflow", ["static-production", "static-app-release"])
@pytest.mark.parametrize("status", ["queued", "waiting", "pending", "requested",
                                    "in_progress", "unknown"])
def test_every_other_inflight_run_blocks(idle_operator, workflow, status):
    op, responses = idle_operator
    page = responses[f"actions/workflows/{workflow}.yml/runs?per_page=100&page=1"]
    page["workflow_runs"].append({"id": 999, "status": status})
    page["total_count"] += 1
    with pytest.raises(app.Blocked):
        op.idle()


@pytest.mark.parametrize("field,value", [
    ("run_attempt", 1), ("workflow_id", 789), ("path", ".github/workflows/other.yml"),
    ("head_sha", "f" * 40), ("head_branch", "feature"), ("event", "release"),
    ("status", "queued"), ("status", "completed"), ("repository", {"id": 1}),
    ("head_repository", {"id": 1}),
])
def test_own_run_exception_requires_exact_live_identity(idle_operator, field, value):
    op, responses = idle_operator
    responses["actions/runs/123"][field] = value
    with pytest.raises(app.Blocked):
        op.idle()


@pytest.mark.parametrize("failure", ["missing", "duplicate", "incomplete", "changed-total"])
def test_incomplete_or_unstable_app_inventory_blocks(idle_operator, failure):
    op, responses = idle_operator
    page = responses["actions/workflows/static-app-release.yml/runs?per_page=100&page=1"]
    if failure == "missing":
        page.update(total_count=0, workflow_runs=[])
    elif failure == "duplicate":
        page["workflow_runs"] *= 2
        page["total_count"] = 2
    elif failure == "incomplete":
        page["total_count"] = 2
    else:
        page["workflow_runs"] += [{"id": 1000 + i, "status": "completed"} for i in range(99)]
        page["total_count"] = 101
        responses["actions/workflows/static-app-release.yml/runs?per_page=100&page=2"] = {
            "total_count": 102, "workflow_runs": [{"id": 2000, "status": "completed"}]}
    with pytest.raises(app.Blocked):
        op.idle()


def test_other_run_on_later_page_is_not_lost(idle_operator):
    op, responses = idle_operator
    page = responses["actions/workflows/static-app-release.yml/runs?per_page=100&page=1"]
    page["workflow_runs"] += [{"id": 1000 + i, "status": "completed"} for i in range(99)]
    page["total_count"] = 101
    responses["actions/workflows/static-app-release.yml/runs?per_page=100&page=2"] = {
        "total_count": 101, "workflow_runs": [{"id": 2000, "status": "waiting"}]}
    with pytest.raises(app.Blocked):
        op.idle()


@pytest.mark.parametrize("endpoint,method,body", [
    ("actions/variables/STATIC_APPROVED_SHA", "PATCH", {"value": bundle.CANDIDATE}),
    ("actions/workflows/static-production.yml/disable", "PUT", None),
    ("actions/variables/STATIC_AUTOMATION_ENABLED", "PATCH",
     {"name": "STATIC_AUTOMATION_ENABLED", "value": "true"}),
])
def test_no_other_mutation_even_when_pause_is_authorized(idle_operator, endpoint, method, body):
    op, _ = idle_operator
    op.pause_allowed = True
    with pytest.raises(app.Blocked):
        op.gh(endpoint, method, body)
    with pytest.raises(app.Blocked):
        op.upload(None)
    with pytest.raises(app.Blocked):
        op.set_workflow(True)


@pytest.fixture
def transport(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    monkeypatch.setattr(bundle, "EVIDENCE_ROOT", tmp_path / "restored-evidence")
    record = {"schema_version": 1, "kind": "forecast-model-selection",
              "sha": bundle.CANDIDATE, "current_sha": bundle.CURRENT,
              "tooling_sha": bundle.TOOLING, "project": "PRIVATE-CONFIG-SENTINEL", "checks": {}}
    identity = {key: value for key, value in record.items() if key != "checks"}
    for role in bundle.ROLES:
        report = json.dumps({"identity": identity, "check": role, "result": "PASS",
                             "reviewed_by": "synthetic-reviewer", "summary": "synthetic only"},
                            indent=2).encode() + b"\r\n"
        name = role + ".json"
        bundle.write_private(source / name, report)
        record["checks"][role] = {"result": "PASS", "reviewed_by": "synthetic-reviewer",
            "summary": "synthetic only", "record": {"path": name, "sha256": bundle.sha256(report)}}
    raw = json.dumps(record, indent=3).encode() + b"\n"
    bundle.write_private(source / bundle.RECORD_NAME, raw)
    monkeypatch.setattr(bundle, "RECORD_SHA256", bundle.sha256(raw))
    destination = tmp_path / "transport"
    bundle.pack(source / bundle.RECORD_NAME, destination)
    secret = (destination / "evidence.secret").read_text()
    key = bundle.key_bytes((destination / "archive.key").read_text())
    files = bundle.open_secret(secret, key, datetime.now(UTC))
    return source, destination, secret, key, files


def test_secret_roundtrip_preserves_every_original_byte_and_private_modes(transport):
    source, destination, secret, _, files = transport
    assert len(secret) <= bundle.MAX_SECRET
    for name, raw in files.items():
        assert raw == (source / name).read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o700
    for path in destination.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("change", ["missing-report", "report-bytes", "record-bytes",
                                    "key", "expired", "size", "bomb"])
def test_transport_failures_before_any_provider_work(transport, change, monkeypatch):
    _, _, secret, key, _ = transport
    envelope = json.loads(gzip.decompress(base64.b64decode(secret)))
    if change == "missing-report":
        del envelope["reports"][bundle.ROLES[0]]
    elif change == "report-bytes":
        envelope["reports"][bundle.ROLES[0]] = base64.b64encode(b"changed").decode()
    elif change == "record-bytes":
        envelope["record"] += "YQ=="
    elif change == "key":
        key = os.urandom(32)
    elif change == "expired":
        before = datetime.now(UTC) - timedelta(days=2)
        envelope.update(created_at=before.isoformat(),
                        expires_at=(before + timedelta(hours=24)).isoformat())
    elif change == "size":
        monkeypatch.setattr(bundle, "MAX_SECRET", 5)
    else:
        monkeypatch.setattr(bundle, "MAX_ENVELOPE", 100)
    secret = base64.b64encode(gzip.compress(json.dumps(envelope).encode())).decode()
    with pytest.raises((bundle.InvalidBundle, ValueError)):
        bundle.open_secret(secret, key, datetime.now(UTC))


@pytest.mark.parametrize("path", ["../outside.json", "/tmp/outside.json",
                                  "SCHEMA_RECORD.json", "a/../b.json", "a\\b.json"])
def test_evidence_cannot_escape_known_directory(transport, path):
    _, _, _, _, files = transport
    record = json.loads(files[bundle.RECORD_NAME])
    record["checks"][bundle.ROLES[0]]["record"]["path"] = path
    with pytest.raises((bundle.InvalidBundle, ValueError)):
        bundle.report_names(record)


def test_original_absolute_report_paths_are_supported(transport):
    _, _, _, _, files = transport
    record = json.loads(files[bundle.RECORD_NAME])
    for check in record["checks"].values():
        check["record"]["path"] = str(bundle.EVIDENCE_ROOT / check["record"]["path"])
    assert set(bundle.report_names(record).values()) == {role + ".json" for role in bundle.ROLES}


@pytest.fixture
def simulated(tmp_path, monkeypatch, context):
    env, _, _ = context
    op = driver.manual_operator(app, tmp_path, env)
    state = {"automation": "true", "fail": None, "calls": [], "snapshots": 0}
    def gh(self, endpoint, method="GET", body=None):
        if endpoint == "releases/tags/v2.3.1":
            return {"tag_name": "v2.3.1", "draft": False, "prerelease": False,
                    "published_at": "2026-11-10T00:00:00Z"}
        if endpoint.startswith("actions/runs/"):
            return {"head_sha": bundle.CANDIDATE, "status": "completed", "conclusion": "success",
                    "path": ".github/workflows/test.yml", "repository": {"id": driver.REPO_ID}}
        assert endpoint == "actions/variables/STATIC_AUTOMATION_ENABLED"
        state["calls"].append(method)
        if method == "PATCH":
            state["automation"] = body["value"]
            if state["fail"] == "pause-response":
                raise app.Blocked("Private provider response must never be logged")
        if method == "GET" and state["fail"] == "pause-readback":
            raise app.Blocked("Private readback error")
        return {"value": state["automation"]}
    def git(self, *args):
        if args == ("rev-parse", "HEAD"):
            return bundle.TOOLING
        if args == ("rev-parse", "FETCH_HEAD^{commit}"):
            return "f" * 40 if state["fail"] == "candidate" else bundle.CANDIDATE
        if args[0] == "show":
            return "2.3.1"
        assert args[0] == "fetch"
        return ""
    def compatibility(self, *args):
        state["calls"].append("reviewed-schema-and-live-rules")
        self.schema_receipt = {"path": str(bundle.EVIDENCE_ROOT / bundle.RECORD_NAME),
                               "record": {"private": "PRIVATE-CONFIG-SENTINEL"}}
        self.rules_receipt = {"release": "PRIVATE-RULES-SENTINEL"}
        return "private-rules-digest"
    def snapshot(self, sha, current, *, paused=False):
        state["snapshots"] += 1
        state["calls"].append("snapshot")
        if state["fail"] == "preflight" or (
                state["fail"] == "post-pause" and state["automation"] == "false"):
            raise app.Blocked("Private snapshot error")
        if self.schema_transition:
            app.require(state["automation"] == "false", "Pause required")
        rules = self.compatibility(sha, current, {})
        return {"variables": {"STATIC_AUTOMATION_ENABLED": state["automation"]},
                "schema_receipt": self.schema_receipt, "rules_receipt": self.rules_receipt,
                "rules_digest": rules, "target": {"id": "synthetic-pages"},
                "tooling_sha": bundle.TOOLING}
    def build(self, sha, snapshot, destination):
        state["calls"].append("build")
        if state["fail"] == "build":
            raise app.Blocked("Private build error")
        bundle.write_private(destination / "upload/dist-static/release.json", b'{"test":true}')
        bundle.write_private(destination / "feed-report.json", b'{"test":true}')
    monkeypatch.setattr(app.Operator, "gh", gh)
    monkeypatch.setattr(app.Operator, "git", git)
    monkeypatch.setattr(app.Operator, "snapshot", snapshot)
    monkeypatch.setattr(app.Operator, "compatibility", compatibility)
    monkeypatch.setattr(app.Operator, "build", build)
    store = tmp_path / "store"
    store.mkdir(mode=0o700)
    status = tmp_path / "status.json"
    journal = driver.quiet_journal(app, store, status)
    return op, state, store, journal, status


def test_prepare_pauses_after_full_prechecks_and_keeps_automation_paused(simulated, capsys):
    op, state, store, journal, status = simulated
    plan = driver.execute(app, op, store, journal)
    assert state["automation"] == "false"
    assert state["calls"].count("PATCH") == 1
    assert state["calls"].index("reviewed-schema-and-live-rules") < state["calls"].index("PATCH")
    positions = [state["calls"].index(name) for name in ("PATCH", "GET", "build")]
    assert positions == sorted(positions)
    assert plan["snapshot"]["schema_receipt"] and plan["snapshot"]["rules_receipt"]
    assert json.loads(status.read_text())["automation"] == "CONFIRMED"
    assert "PRIVATE" not in status.read_text()
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("failure,mutation,build", [
    ("candidate", "UNCHANGED", False), ("preflight", "UNCHANGED", False),
    ("pause-response", "UNKNOWN", False), ("pause-readback", "UNKNOWN", False),
    ("post-pause", "CONFIRMED", False), ("build", "CONFIRMED", True),
])
def test_failure_boundaries_never_resume_or_publish(simulated, failure, mutation, build, capsys):
    op, state, store, journal, status = simulated
    state["fail"] = failure
    with pytest.raises(app.Blocked):
        driver.execute(app, op, store, journal)
    journal.finish(False)
    assert journal.value["changes"]["automation"] == mutation
    assert ("build" in state["calls"]) == build
    assert state["automation"] == ("true" if mutation == "UNCHANGED" else "false")
    assert not op.pause_allowed and not (store / "plan.json").exists()
    assert "PRIVATE" not in status.read_text()
    assert capsys.readouterr() == ("", "")


def test_explicit_retry_when_already_paused_does_not_write_again(simulated):
    op, state, store, journal, _ = simulated
    state["automation"] = "false"
    driver.execute(app, op, store, journal)
    assert "PATCH" not in state["calls"] and state["automation"] == "false"


@pytest.fixture
def archive(transport, simulated, tmp_path):
    _, destination, _, key, files = transport
    op, state, store, journal, _ = simulated
    driver.execute(app, op, store, journal)
    raw = (store / "plan.json").read_bytes()
    handoff = {"sha": bundle.CANDIDATE, "current_sha": bundle.CURRENT,
               "tooling_sha": bundle.TOOLING, "prepared": True, "plan_sha256": bundle.sha256(raw)}
    bundle.write_private(store / "handoff.json", json.dumps(handoff).encode())
    bundle.write_private(store / "prepared/app/.git/config", b"MUST-NOT-BE-ARCHIVED")
    bundle.write_private(store / "prepared/cache/secret", b"MUST-NOT-BE-ARCHIVED")
    output = tmp_path / "result.aesgcm"
    bundle.seal(store, files, key, output, success=True)
    return output, destination / "archive.key", files, raw


def test_encrypted_handoff_is_reusable_without_rewriting_plan_or_evidence(archive, tmp_path):
    output, key, files, plan = archive
    ciphertext = output.read_bytes()
    assert b"PRIVATE" not in ciphertext and b"plan.json" not in ciphertext
    assert not zipfile.is_zipfile(output)
    destination = tmp_path / "restored-store"
    result = bundle.unseal(output, key, destination)
    assert result["within_plan_window"]
    assert (destination / "plan.json").read_bytes() == plan
    assert (destination / "prepared/feed-report.json").exists()
    assert not (destination / "prepared/app").exists()
    assert not (destination / "prepared/cache").exists()
    for name, raw in files.items():
        assert (bundle.EVIDENCE_ROOT / name).read_bytes() == raw
        assert (bundle.EVIDENCE_ROOT / name).stat().st_mode & 0o077 == 0
    assert destination.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("change", ["ciphertext", "key"])
def test_failed_authentication_writes_no_plaintext(archive, tmp_path, change):
    output, key, _, _ = archive
    if change == "ciphertext":
        value = bytearray(output.read_bytes())
        value[-1] ^= 1
        output.write_bytes(value)
    else:
        key.write_text(base64.b64encode(os.urandom(32)).decode())
    destination = tmp_path / "blocked-store"
    with pytest.raises(InvalidTag):
        bundle.unseal(output, key, destination)
    assert not destination.exists() and not bundle.EVIDENCE_ROOT.exists()


def test_restore_refuses_conflicting_original_evidence(archive, tmp_path):
    output, key, files, _ = archive
    bundle.restore_evidence(files)
    (bundle.EVIDENCE_ROOT / bundle.RECORD_NAME).write_bytes(b"unrelated existing record")
    with pytest.raises(bundle.InvalidBundle):
        bundle.unseal(output, key, tmp_path / "blocked-store")
    assert (bundle.EVIDENCE_ROOT / bundle.RECORD_NAME).read_bytes() == b"unrelated existing record"


def test_archive_capacity_and_symlink_boundaries(transport, simulated, tmp_path, monkeypatch):
    _, _, _, key, files = transport
    op, _, store, journal, _ = simulated
    driver.execute(app, op, store, journal)
    bundle.write_private(store / "handoff.json", b"{}")
    output = tmp_path / "limited.aesgcm"
    monkeypatch.setattr(bundle, "MAX_PAYLOAD", 100)
    with pytest.raises(bundle.InvalidBundle, match="archive-capacity"):
        bundle.seal(store, files, key, output, success=True)
    assert not output.exists()
    monkeypatch.setattr(bundle, "MAX_PAYLOAD", 240 * 1024 * 1024)
    (store / "prepared/upload/escape").symlink_to(tmp_path)
    with pytest.raises(bundle.InvalidBundle, match="symlink"):
        bundle.seal(store, files, key, output, success=True)
    assert not output.exists()


def test_authenticated_archive_still_rejects_traversal(archive, tmp_path):
    output, key_path, _, _ = archive
    key = bundle.key_bytes(key_path.read_text())
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as zipped:
        zipped.writestr("store/../../escape", b"bad")
    nonce = os.urandom(12)
    output.write_bytes(bundle.MAGIC + nonce + AESGCM(key).encrypt(
        nonce, content.getvalue(), bundle.MAGIC))
    with pytest.raises(bundle.InvalidBundle):
        bundle.unseal(output, key_path, tmp_path / "blocked-store")
    assert not (tmp_path / "escape").exists()


def test_cli_has_no_publish_mode_and_errors_do_not_expose_inputs(tmp_path):
    source = Path(driver.__file__)
    result = subprocess.run([sys.executable, str(source), "publish"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    result = subprocess.run([sys.executable, str(bundle.__file__), "unpack",
                             "--archive", str(tmp_path / "missing"),
                             "--key", str(tmp_path / "secret-key"),
                             "--store", str(tmp_path / "store")], capture_output=True, text=True)
    assert result.returncode != 0 and result.stdout == ""
    assert "secret-key" not in result.stderr and "Traceback" not in result.stderr


def test_workflow_manual_prepare_is_disjoint_and_only_uploads_ciphertext():
    workflow = (Path(__file__).resolve().parents[2]
                / ".github/workflows/static-app-release.yml").read_text()
    manual = workflow.split("\n  manual-prepare:\n", 1)[1].split("\n  manual-publish:\n", 1)[0]
    condition = " ".join(manual.split("    if: >-\n", 1)[1]
                         .split("\n    runs-on:", 1)[0].split())
    assert condition == (
        "github.repository == 'Yuto-24/NavMate' && github.event_name == 'workflow_dispatch' && "
        "github.ref == 'refs/heads/main' && inputs.operation == 'prepare-schema431' && "
        "inputs.release_id == ''")
    assert "environment: static-production" in manual
    assert "ref: " + bundle.TOOLING in manual and "ref: ${{ github.sha }}" in manual
    assert "secrets.STATIC_CLOUDFLARE_READ_TOKEN" in manual
    assert "secrets.CLOUDFLARE_PAGES_TOKEN" not in manual and "release_automation.py" not in manual
    assert "retention-days: 1" in manual and "if-no-files-found: error" in manual
    assert ".aesgcm" in manual and "plan.json" not in manual
    assert "steps.prepare.outputs.archive_ready == 'true'" in manual
    assert "create_credentials_file: false" in manual
    assert "https://www.googleapis.com/auth/firebase.readonly" in manual
    assert "group: static-production\n  cancel-in-progress: false\n  queue: max" in workflow


@pytest.fixture
def runner_environment(transport, simulated, context, tmp_path, monkeypatch):
    _, _, secret, key, _ = transport
    _, state, _, _, _ = simulated
    env, event, _ = context
    event_path, outputs = tmp_path / "event.json", tmp_path / "outputs"
    event_path.write_text(json.dumps(event))
    outputs.touch()
    env.update(RUNNER_TEMP=str(tmp_path), GITHUB_EVENT_PATH=str(event_path),
               GITHUB_OUTPUT=str(outputs), GH_TOKEN="SECRET-TOKEN-SENTINEL",
               CLOUDFLARE_API_TOKEN="SECRET-TOKEN-SENTINEL",
               STATIC_GOOGLE_ACCESS_TOKEN="SECRET-TOKEN-SENTINEL")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SCHEMA431_EVIDENCE", secret)
    monkeypatch.setenv("SCHEMA431_ARCHIVE_KEY", base64.b64encode(key).decode())
    monkeypatch.setattr(driver.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(driver, "checked_checkout", lambda root, sha: None)
    def load(root):
        assert "SCHEMA431_EVIDENCE" not in os.environ
        assert "SCHEMA431_ARCHIVE_KEY" not in os.environ
        return app
    monkeypatch.setattr(driver, "load_tooling", load)
    previous_umask = os.umask(0o022)
    try:
        yield env, state, outputs
    finally:
        os.umask(previous_umask)


@pytest.mark.parametrize("failure", [None, "preflight", "pause-response", "build"])
def test_runner_retains_encrypted_recovery_and_removes_plaintext(
        runner_environment, tmp_path, capsys, failure):
    env, state, outputs = runner_environment
    state["fail"] = failure
    result = driver.run(tmp_path)
    store, output, status_path = driver.locations(env)
    assert result == (0 if failure is None else 1)
    assert output.is_file() and not store.exists() and not bundle.EVIDENCE_ROOT.exists()
    status = json.loads(status_path.read_text())
    assert status["archive_ready"] and "PRIVATE" not in status_path.read_text()
    assert "SECRET-TOKEN" not in output.read_bytes().decode("latin-1")
    assert outputs.read_text() == "archive_ready=true\n"
    assert output.stat().st_mode & 0o777 == 0o600
    ordinary_file = tmp_path / "subsequent-coverage"
    ordinary_file.touch()
    assert ordinary_file.stat().st_mode & 0o777 == 0o644
    if failure in ("pause-response", "build"):
        assert state["automation"] == "false"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("diagnostic_fault", [None, "extraction", "write"])
def test_command_failure_details_survive_only_in_encrypted_recovery(
        runner_environment, transport, tmp_path, monkeypatch, capsys, diagnostic_fault):
    env, state, _ = runner_environment
    _, packed, _, _, _ = transport
    calls = []
    args = ["docker", "build", "-f", "scripts/static_ops/Dockerfile.build", "-t",
            "autonavlog-static-release:" + bundle.TOOLING, "."]
    def build(self, sha, snapshot, destination):
        app.command(args, cwd=tmp_path)
    def run(actual, **kwargs):
        calls.append(actual)
        return subprocess.CompletedProcess(actual, 9, "PRIVATE-BUILD-DETAIL",
                                           "PRIVATE-ERROR SECRET-TOKEN-SENTINEL")
    monkeypatch.setattr(app.Operator, "build", build)
    monkeypatch.setattr(app.subprocess, "run", run)
    if diagnostic_fault == "extraction":
        monkeypatch.setattr(driver.diagnostics, "private_tail", lambda *a, **kw: 1 / 0)
    elif diagnostic_fault == "write":
        original_save = app.Journal.save
        def save(journal):
            if "failure" in journal.value:
                raise OSError("Synthetic diagnostic write failure")
            original_save(journal)
        monkeypatch.setattr(app.Journal, "save", save)
    assert driver.run(tmp_path) == 1
    store, output, status = driver.locations(env)
    assert calls == [args] and state["automation"] == "false"
    assert not store.exists() and not bundle.EVIDENCE_ROOT.exists()
    assert "PRIVATE" not in status.read_text() and b"PRIVATE" not in output.read_bytes()
    restored = tmp_path / "recovery"
    result = bundle.unseal(output, packed / "archive.key", restored)
    assert not result["prepared"] and result["plan_sha256"] is None
    recovered = json.loads((restored / "prepare-status.json").read_text())
    assert recovered["status"] == "BLOCKED" and recovered["stage"] == "build-test"
    if diagnostic_fault is None:
        assert recovered["failure"]["command"]["returncode"] == 9
        assert recovered["failure"]["command"]["stdout"]["tail"] == "PRIVATE-BUILD-DETAIL"
        assert recovered["failure"]["command"]["stderr"]["tail"] == "PRIVATE-ERROR [REDACTED]"
    else:
        assert "failure" not in recovered
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("failure", ["locations", "initial-status"])
def test_run_restores_creation_permissions_after_initialization_exception(
        runner_environment, tmp_path, monkeypatch, failure):
    if failure == "locations":
        monkeypatch.delenv("GITHUB_RUN_ID")
    else:
        def fail_status(*args):
            raise OSError("Synthetic status write failure")
        monkeypatch.setattr(driver, "public_status", fail_status)
    with pytest.raises((bundle.InvalidBundle, OSError)):
        driver.run(tmp_path)
    ordinary_file = tmp_path / "subsequent-coverage"
    ordinary_file.touch()
    assert ordinary_file.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize("failure", ["journal-status", "handoff", "sealed-status"])
def test_finalization_faults_preserve_output_and_cleanup(
        runner_environment, tmp_path, monkeypatch, failure):
    env, _, outputs = runner_environment
    store, output, status_path = driver.locations(env)
    write_status, write_json = driver.public_status, app.write_json

    def status(path, value):
        if (failure == "journal-status" and value["status"] == "RUNNING") or (
                failure == "sealed-status" and output.exists()):
            raise OSError("Synthetic status write failure")
        write_status(path, value)

    def handoff(path, value):
        if failure == "handoff" and path.name == "handoff.json":
            raise OSError("Synthetic handoff write failure")
        write_json(path, value)

    monkeypatch.setattr(driver, "public_status", status)
    monkeypatch.setattr(app, "write_json", handoff)
    if failure == "journal-status":
        assert driver.run(tmp_path) == 1
    else:
        with pytest.raises(OSError):
            driver.run(tmp_path)
    assert not store.exists() and not bundle.EVIDENCE_ROOT.exists()
    assert output.exists() == (failure == "sealed-status")
    assert outputs.read_text() == (
        "archive_ready=true\n" if failure == "sealed-status" else "archive_ready=false\n")
    if failure != "sealed-status":
        assert json.loads(status_path.read_text())["status"] == "BLOCKED"
    ordinary_file = tmp_path / "subsequent-coverage"
    ordinary_file.touch()
    assert ordinary_file.stat().st_mode & 0o777 == 0o644


def test_original_record_hash_and_tooling_cannot_be_overridden_by_cli():
    assert bundle.RECORD_SHA256 == (
        "d384f6619038a2b55a30abf6b08ecd88d9d7aede5292963414fd52d433f9be4d")
    assert bundle.TOOLING == "64225b82c9b2e978409f0b35490be3c83af3f157"


def test_root_owned_build_cleanup_preserves_a_fixed_scope(tmp_path, monkeypatch):
    if os.getuid() == 0:
        pytest.skip("The DAC regression requires the same nonroot role as the Actions runner")
    env = {"RUNNER_TEMP": str(tmp_path), "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
    store, _, _ = driver.locations(env)
    locked = store / "prepared/app/node_modules"
    locked.mkdir(parents=True, mode=0o700)
    store.chmod(0o700)
    (locked / "file").write_text("synthetic root-owned-equivalent directory")
    locked.chmod(0o555)
    calls = []
    def privileged(args, **kwargs):
        calls.append((args, kwargs))
        assert args == ["sudo", "-n", "rm", "-rf", "--", str(store)]
        assert kwargs["env"] == {"PATH": os.defpath}
        assert kwargs["capture_output"] and kwargs["timeout"] == 120
        locked.chmod(0o700)
        driver.shutil.rmtree(store)
    monkeypatch.setattr(driver.subprocess, "run", privileged)
    try:
        driver.cleanup_store(store, env)
        assert len(calls) == 1 and not store.exists()
    finally:
        if locked.exists():
            locked.chmod(0o700)


def test_cleanup_rejects_unowned_path_or_symlink(tmp_path):
    env = {"RUNNER_TEMP": str(tmp_path), "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
    other = tmp_path / "unrelated"
    other.mkdir(mode=0o700)
    with pytest.raises(bundle.InvalidBundle):
        driver.cleanup_store(other, env)
    expected, _, _ = driver.locations(env)
    expected.symlink_to(other)
    with pytest.raises(bundle.InvalidBundle):
        driver.cleanup_store(expected, env)
    assert other.exists()


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_archive_output_is_recorded_before_cleanup_even_when_cleanup_fails(
        runner_environment, tmp_path, monkeypatch, cleanup_failure):
    env, _, outputs = runner_environment
    def cleanup(store, actual_env):
        assert outputs.read_text() == "archive_ready=true\n"
        if cleanup_failure:
            raise PermissionError("Synthetic ordinary and privileged cleanup failure")
        driver.shutil.rmtree(store)
    monkeypatch.setattr(driver, "cleanup_store", cleanup)
    assert driver.run(tmp_path) == int(cleanup_failure)
    _, output, status_path = driver.locations(env)
    assert output.exists() and outputs.read_text() == "archive_ready=true\n"
    status = json.loads(status_path.read_text())
    assert status["cleanup"] == ("FAILED" if cleanup_failure else "COMPLETE")
    assert status["archive_ready"] is True


@pytest.mark.parametrize("failure", ["sha", "dirty", "remote"])
def test_tooling_checkout_is_rejected_before_import(tmp_path, monkeypatch, failure):
    def git(args, **kwargs):
        if args[1] == "rev-parse":
            result = "a" * 40 if failure == "sha" else bundle.TOOLING
        elif args[1] == "status":
            result = " M scripts/static_ops/app_release.py" if failure == "dirty" else ""
        else:
            result = "https://example.invalid/repo" if failure == "remote" else (
                "https://github.com/" + driver.REPO + ".git")
        return subprocess.CompletedProcess(args, 0, result)
    monkeypatch.setattr(driver.subprocess, "run", git)
    monkeypatch.setattr(driver.importlib, "import_module", lambda *args: pytest.fail(
        "Unverified code must not be imported"))
    with pytest.raises(bundle.InvalidBundle):
        driver.load_tooling(tmp_path)
