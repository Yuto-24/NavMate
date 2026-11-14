"""Explicit schema publication: original plan, strict provenance and private recovery."""

import base64
import copy
import io
import json
import os
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.static_ops import app_release as app
from scripts.static_ops import schema431_bundle as bundle
from scripts.static_ops import schema431_prepare as prepare
from scripts.static_ops import schema431_publish as driver
from tests.unit import test_schema431_prepare as prepare_tests
from tests.unit.test_static_app_release import SimulatedOperator

context = prepare_tests.context
transport = prepare_tests.transport


@pytest.fixture
def publication_context(context):
    env, event, source = copy.deepcopy(context)
    source.update(status="completed", conclusion="success", display_title="schema431-prepare")
    env.update(GITHUB_JOB="manual-publish", GITHUB_RUN_ID="345", GITHUB_RUN_ATTEMPT="1")
    event["inputs"] = {"operation": driver.OPERATION, "release_id": "",
                       "prepare_run_id": "123", "prepare_run_attempt": "2",
                       "reviewed_plan_sha256": "a" * 64}
    return env, event, source


def test_publish_requires_separate_explicit_dispatch(publication_context):
    env, event, _ = publication_context
    assert driver.scope(env, event) == event["inputs"]
    with pytest.raises(bundle.InvalidBundle):
        prepare.scope(env, event)


@pytest.mark.parametrize("name,value", [
    ("prepare_run_id", ""), ("prepare_run_id", "345"), ("prepare_run_id", "../123"),
    ("prepare_run_attempt", "0"), ("reviewed_plan_sha256", ""),
    ("reviewed_plan_sha256", "A" * 64), ("reviewed_plan_sha256", "a" * 63),
    ("operation", "replay-release"), ("operation", "prepare-schema431"), ("release_id", "1"),
])
def test_missing_or_ambiguous_approval_blocks(publication_context, name, value):
    env, event, _ = publication_context
    event["inputs"][name] = value
    with pytest.raises(bundle.InvalidBundle):
        driver.scope(env, event)


@pytest.mark.parametrize("name,value", [
    ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_JOB", "publish"),
    ("GITHUB_EVENT_NAME", "release"), ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_REPOSITORY_ID", "1"), ("GITHUB_WORKFLOW_SHA", "b" * 40),
])
def test_reruns_and_other_execution_contexts_block(publication_context, name, value):
    env, event, _ = publication_context
    env[name] = value
    with pytest.raises(bundle.InvalidBundle):
        driver.scope(env, event)


@pytest.fixture
def provenance(publication_context, tmp_path, monkeypatch):
    env, event, source = publication_context
    operator = driver.publication_operator(app, tmp_path, env)
    job = {"id": 9, "run_id": 123, "run_attempt": 2, "head_sha": source["head_sha"],
           "name": "manual-prepare", "status": "completed", "conclusion": "success"}
    artifact = {"id": 77, "name": "schema431-123-2", "expired": False, "size_in_bytes": 200,
                "workflow_run": {"id": 123, "repository_id": prepare.REPO_ID,
                                 "head_repository_id": prepare.REPO_ID, "head_branch": "main",
                                 "head_sha": source["head_sha"]}}
    responses = {
        "actions/runs/123": source,
        "actions/workflows/static-app-release.yml": {
            "id": 456, "path": prepare.WORKFLOW, "state": "active"},
        "actions/runs/123/attempts/2/jobs?per_page=100&page=1": {"total_count": 1, "jobs": [job]},
        "actions/runs/123/artifacts?name=schema431-123-2&per_page=100&page=1": {
            "total_count": 1, "artifacts": [artifact]},
    }
    def gh(self, endpoint, method="GET", body=None):
        assert method == "GET"
        return copy.deepcopy(responses[endpoint])
    monkeypatch.setattr(app.Operator, "gh", gh)
    return operator, event["inputs"], responses, source, job, artifact


def test_exact_successful_prepare_attempt_is_required(provenance):
    operator, inputs, _, source, _, _ = provenance
    assert driver.source_run(operator, inputs) == source


@pytest.fixture(params=["manual-prepare", "skipped"])
def optional_job_attempt(provenance, request):
    operator, inputs, responses, source, job, _ = provenance
    if request.param == "skipped":
        job = {**job, "id": 10, "name": "publish", "conclusion": "skipped"}
        listing = responses["actions/runs/123/attempts/2/jobs?per_page=100&page=1"]
        listing["jobs"].append(job)
        listing["total_count"] = 2
    return operator, inputs, source, job


def test_attempt_scoped_jobs_accept_an_omitted_optional_attempt(optional_job_attempt):
    operator, inputs, source, job = optional_job_attempt
    del job["run_attempt"]
    assert driver.source_run(operator, inputs) == source


@pytest.mark.parametrize("value", [None, True, "2", 1, 3])
def test_present_job_attempt_must_still_be_the_exact_integer(optional_job_attempt, value):
    operator, inputs, _, job = optional_job_attempt
    job["run_attempt"] = value
    with pytest.raises(bundle.InvalidBundle, match="prepare-job-identity"):
        driver.source_run(operator, inputs)


@pytest.mark.parametrize("value", ["missing", None, True, "2", 3])
def test_optional_job_attempt_does_not_weaken_the_latest_run_check(provenance, value):
    operator, inputs, _, source, job, _ = provenance
    del job["run_attempt"]
    if value == "missing":
        del source["run_attempt"]
    else:
        source["run_attempt"] = value
    with pytest.raises(bundle.InvalidBundle, match="prepare-run-identity"):
        driver.source_run(operator, inputs)


@pytest.mark.parametrize("field,value", [("run_id", 345), ("head_sha", "f" * 40)])
def test_optional_job_attempt_keeps_run_and_source_checks(provenance, field, value):
    operator, inputs, _, _, job, _ = provenance
    del job["run_attempt"]
    job[field] = value
    with pytest.raises(bundle.InvalidBundle, match="prepare-job-identity"):
        driver.source_run(operator, inputs)


@pytest.mark.parametrize("name,value", [
    ("run_attempt", 3), ("status", "queued"), ("conclusion", "failure"),
    ("head_branch", "feature"), ("workflow_id", 999), ("head_sha", "bad"),
    ("event", "release"), ("path", ".github/workflows/other.yml"),
    ("display_title", "schema431-publish"), ("repository", {"id": 1}),
    ("head_repository", {"id": 1}),
])
def test_foreign_or_changed_source_is_rejected(provenance, name, value):
    operator, inputs, _, source, _, _ = provenance
    source[name] = value
    with pytest.raises(bundle.InvalidBundle):
        driver.source_run(operator, inputs)


@pytest.mark.parametrize("name,value", [
    ("run_attempt", 1), ("run_id", 345), ("head_sha", "f" * 40),
    ("name", "publish"), ("status", "queued"), ("conclusion", "skipped"),
])
def test_prepare_job_must_have_completed_in_that_attempt(provenance, name, value):
    operator, inputs, _, _, job, _ = provenance
    job[name] = value
    with pytest.raises(bundle.InvalidBundle):
        driver.source_run(operator, inputs)


@pytest.mark.parametrize("failure", ["incomplete", "duplicate", "changed-total", "second-prepare"])
def test_every_job_page_is_validated(provenance, failure):
    operator, inputs, responses, _, job, _ = provenance
    first = responses["actions/runs/123/attempts/2/jobs?per_page=100&page=1"]
    first["jobs"] += [{**job, "id": i, "name": "skipped-" + str(i)} for i in range(100, 199)]
    first["total_count"] = 101
    second = {"total_count": 101, "jobs": [{**job, "id": 200, "name": "skipped"}]}
    responses["actions/runs/123/attempts/2/jobs?per_page=100&page=2"] = second
    assert driver.source_run(operator, inputs)
    if failure == "incomplete":
        second["jobs"] = []
    elif failure == "duplicate":
        second["jobs"][0]["id"] = 9
    elif failure == "changed-total":
        second["total_count"] = 102
    else:
        second["jobs"][0]["name"] = "manual-prepare"
    with pytest.raises(bundle.InvalidBundle):
        driver.source_run(operator, inputs)


@pytest.fixture
def download_mock(monkeypatch):
    files = {"schema431-result-123-2.aesgcm": b"ciphertext"}
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert args[-1] == "repos/Yuto-24/NavMate/actions/artifacts/77/zip"
        assert "STATIC_GOOGLE_ACCESS_TOKEN" not in kwargs["env"]
        assert "CLOUDFLARE_API_TOKEN" not in kwargs["env"]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
        kwargs["stdout"].write(buffer.getvalue())
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(driver.subprocess, "run", run)
    return files, calls


def test_download_extracts_only_the_expected_ciphertext(provenance, download_mock, tmp_path):
    operator, inputs, _, source, _, _ = provenance
    output, actual_source = driver.download(operator, inputs, tmp_path)
    assert output.read_bytes() == b"ciphertext" and actual_source == source
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["duplicate", "expired", "oversized", "source", "missing"])
def test_artifact_metadata_blocks_before_download(provenance, download_mock, tmp_path, failure):
    operator, inputs, responses, _, _, artifact = provenance
    listing = responses["actions/runs/123/artifacts?name=schema431-123-2&per_page=100&page=1"]
    if failure == "duplicate":
        listing["total_count"] = 2
    elif failure == "expired":
        artifact["expired"] = True
    elif failure == "oversized":
        artifact["size_in_bytes"] = bundle.MAX_ARCHIVE + 65537
    elif failure == "source":
        artifact["workflow_run"]["head_sha"] = "f" * 40
    else:
        listing["artifacts"] = []
    with pytest.raises(bundle.InvalidBundle):
        driver.download(operator, inputs, tmp_path)
    assert not download_mock[1]


@pytest.mark.parametrize("failure", ["extra", "path", "empty", "size", "rerun"])
def test_archive_and_source_races_block(provenance, download_mock, tmp_path, monkeypatch, failure):
    operator, inputs, _, source, _, _ = provenance
    files, _ = download_mock
    if failure == "extra":
        files["plan.json"] = b"plaintext"
    elif failure == "path":
        files["../outside"] = files.pop("schema431-result-123-2.aesgcm")
    elif failure == "empty":
        files.clear()
    elif failure == "size":
        monkeypatch.setattr(bundle, "MAX_ARCHIVE", 4)
    else:
        download = driver.subprocess.run
        def rerun(*args, **kwargs):
            result = download(*args, **kwargs)
            source["run_attempt"] = 3
            return result
        monkeypatch.setattr(driver.subprocess, "run", rerun)
    with pytest.raises(bundle.InvalidBundle):
        driver.download(operator, inputs, tmp_path)
    assert not (tmp_path.parent / "outside").exists()


@pytest.mark.parametrize("enabled", [False, True])
def test_publication_capabilities_are_exact(provenance, monkeypatch, enabled):
    operator, _, _, _, _, _ = provenance
    calls = []
    monkeypatch.setattr(app.Operator, "gh", lambda self, *args: calls.append(args))
    operator.publication_allowed = enabled
    allowed = [
        ("actions/variables/STATIC_AUTOMATION_ENABLED", "PATCH",
         {"name": "STATIC_AUTOMATION_ENABLED", "value": "false"}),
        ("actions/variables/STATIC_APPROVED_SHA", "PATCH",
         {"name": "STATIC_APPROVED_SHA", "value": bundle.CANDIDATE}),
        ("actions/workflows/static-production.yml/disable", "PUT", None),
        ("actions/workflows/static-production.yml/enable", "PUT", None),
    ]
    for args in allowed:
        if enabled:
            operator.gh(*args)
        else:
            with pytest.raises(app.Blocked):
                operator.gh(*args)
    denied = [
        ("actions/variables/STATIC_AUTOMATION_ENABLED", "PATCH",
         {"name": "STATIC_AUTOMATION_ENABLED", "value": "true"}),
        ("actions/variables/STATIC_APPROVED_SHA", "PATCH",
         {"name": "STATIC_APPROVED_SHA", "value": bundle.CURRENT}),
        ("actions/workflows/static-app-release.yml/disable", "PUT", None),
        ("actions/workflows/static-production.yml/dispatches", "POST", {}),
    ]
    for args in denied:
        with pytest.raises(app.Blocked):
            operator.gh(*args)
    assert calls == (allowed if enabled else [])


def test_publish_snapshot_keeps_identities_and_original_paused_gate(provenance, monkeypatch):
    operator, _, _, _, _, _ = provenance
    calls = []
    monkeypatch.setattr(app.Operator, "git", lambda *args: bundle.TOOLING)
    monkeypatch.setattr(app.Operator, "snapshot", lambda *args, **kwargs: calls.append(kwargs))
    operator.snapshot(bundle.CANDIDATE, bundle.CURRENT, paused=True)
    assert calls == [{"paused": True}]
    for candidate, current in ((bundle.CURRENT, bundle.CURRENT), (bundle.CANDIDATE, "a" * 40)):
        with pytest.raises(app.Blocked):
            operator.snapshot(candidate, current)


@pytest.mark.parametrize("failure", [None, "other-running", "other-queued", "feed-waiting",
                                      "own-attempt", "missing-own", "duplicate"])
def test_publication_reuses_the_strict_own_run_exception(provenance, failure):
    operator, _, responses, source, _, _ = provenance
    own = {**source, "id": 345, "run_attempt": 1, "status": "in_progress"}
    responses["actions/runs/345"] = own
    app_runs = {"total_count": 1, "workflow_runs": [own]}
    feed_runs = {"total_count": 0, "workflow_runs": []}
    responses["actions/workflows/static-app-release.yml/runs?per_page=100&page=1"] = app_runs
    responses["actions/workflows/static-production.yml/runs?per_page=100&page=1"] = feed_runs
    if failure in ("other-running", "other-queued"):
        app_runs["workflow_runs"].append({"id": 999, "status": (
            "in_progress" if failure == "other-running" else "queued")})
        app_runs["total_count"] = 2
    elif failure == "feed-waiting":
        feed_runs.update(total_count=1, workflow_runs=[{"id": 999, "status": "waiting"}])
    elif failure == "own-attempt":
        own["run_attempt"] = 2
    elif failure == "missing-own":
        app_runs.update(total_count=0, workflow_runs=[])
    elif failure == "duplicate":
        app_runs["workflow_runs"].append(own)
        app_runs["total_count"] = 2
    if failure:
        with pytest.raises(app.Blocked):
            operator.idle()
    else:
        operator.idle()


@pytest.fixture
def approved_plan(transport, publication_context, tmp_path):
    _, destination, _, key, files = transport
    _, event, source = publication_context
    operator = SimulatedOperator(tmp_path / "tooling", automation="false")
    operator.state["variables"]["STATIC_APPROVED_SHA"] = bundle.CURRENT
    operator.state["target"]["commit"] = bundle.CURRENT
    operator.state["tooling_sha"] = bundle.TOOLING
    operator.state["schema_receipt"] = {"path": str(bundle.EVIDENCE_ROOT / bundle.RECORD_NAME)}
    store = tmp_path / "approved"
    store.mkdir(mode=0o700)
    status = tmp_path / "prepare-status"
    journal = prepare.quiet_journal(app, store, status)
    plan = app.prepare(operator, bundle.CANDIDATE, bundle.CURRENT, store, journal)
    journal.finish(True)
    raw = (store / "plan.json").read_bytes()
    reviewed = bundle.sha256(raw)
    handoff = {"schema_version": 1, "sha": bundle.CANDIDATE, "current_sha": bundle.CURRENT,
               "tooling_sha": bundle.TOOLING, "driver_sha": source["head_sha"],
               "run_id": "123", "run_attempt": "2", "prepared": True,
               "plan_sha256": reviewed, "prepared_at": plan["prepared_at"]}
    app.write_json(store / "handoff.json", handoff)
    event["inputs"]["reviewed_plan_sha256"] = reviewed
    archive = tmp_path / "prepared.aesgcm"
    bundle.seal(store, files, key, archive, success=True)
    operator.calls.clear()
    return operator, store, reviewed, handoff, archive, destination / "archive.key", raw


@pytest.mark.parametrize("failure", [None, "run", "attempt", "driver", "digest", "bytes",
                                      "expired", "future", "published"])
def test_handoff_keeps_approval_bound_to_original_bytes(
        approved_plan, publication_context, failure):
    _, store, _, handoff, _, _, _ = approved_plan
    _, event, source = publication_context
    if failure in ("run", "attempt", "driver", "digest"):
        key = {"run": "run_id", "attempt": "run_attempt", "driver": "driver_sha",
               "digest": "plan_sha256"}[failure]
        handoff[key] = "changed"
    elif failure == "bytes":
        with (store / "plan.json").open("ab") as stream:
            stream.write(b"\n")
    elif failure in ("expired", "future"):
        plan = json.loads((store / "plan.json").read_text())
        plan["prepared_at"] = (datetime.now(UTC) + timedelta(
            minutes=-31 if failure == "expired" else 1)).isoformat()
        app.write_json(store / "plan.json", plan)
        handoff["prepared_at"] = plan["prepared_at"]
        handoff["plan_sha256"] = bundle.sha256((store / "plan.json").read_bytes())
        event["inputs"]["reviewed_plan_sha256"] = handoff["plan_sha256"]
    elif failure == "published":
        handoff["publication"] = {}
    if failure:
        with pytest.raises(bundle.InvalidBundle):
            driver.validate_handoff(store, handoff, event["inputs"], source)
    else:
        driver.validate_handoff(store, handoff, event["inputs"], source)


@pytest.fixture
def runner(approved_plan, publication_context, tmp_path, monkeypatch):
    operator, _, reviewed, _, archive, key_path, _ = approved_plan
    env, event, source = publication_context
    event_path, outputs = tmp_path / "event.json", tmp_path / "outputs"
    event_path.write_text(json.dumps(event))
    outputs.touch()
    env.update(RUNNER_TEMP=str(tmp_path), GITHUB_EVENT_PATH=str(event_path),
               GITHUB_OUTPUT=str(outputs), GH_TOKEN="SECRET-TOKEN-SENTINEL",
               CLOUDFLARE_API_TOKEN="SECRET-TOKEN-SENTINEL",
               STATIC_GOOGLE_ACCESS_TOKEN="SECRET-TOKEN-SENTINEL")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SCHEMA431_ARCHIVE_KEY", key_path.read_text())
    monkeypatch.setattr(prepare, "checked_checkout", lambda *args: None)
    monkeypatch.setattr(prepare.shutil, "which", lambda name: "/bin/" + name)
    def load(root):
        assert "SCHEMA431_ARCHIVE_KEY" not in os.environ
        return app
    monkeypatch.setattr(prepare, "load_tooling", load)
    monkeypatch.setattr(driver, "publication_operator", lambda *args: operator)
    monkeypatch.setattr(driver, "download", lambda *args: (archive, source))
    monkeypatch.setattr(prepare, "check_candidate", lambda *args: None)
    previous_umask = os.umask(0o022)
    try:
        yield env, operator, outputs, reviewed
    finally:
        os.umask(previous_umask)


@pytest.mark.parametrize("failure", [None, "fresh-build", "upload", "verify", "approve", "enable"])
def test_real_publish_flow_keeps_recovery_private_and_never_resumes(
        runner, approved_plan, tmp_path, capsys, failure):
    env, operator, outputs, _ = runner
    operator.fail = failure
    assert driver.run(tmp_path) == int(failure is not None)
    private, encrypted, status_path = prepare.locations(env)
    assert not private.exists() and not bundle.EVIDENCE_ROOT.exists()
    assert encrypted.is_file() and encrypted.stat().st_mode & 0o777 == 0o600
    assert outputs.read_text() == "archive_ready=true\n"
    assert not operator.publication_allowed and "resume" not in operator.calls
    assert operator.state["variables"]["STATIC_AUTOMATION_ENABLED"] == "false"
    status = json.loads(status_path.read_text())
    assert status["status"] == ("PUBLISHED" if failure is None else "BLOCKED")
    if failure is None:
        assert operator.uploaded.name == "fresh"
        assert operator.state["variables"]["STATIC_APPROVED_SHA"] == bundle.CANDIDATE
    assert "SECRET" not in status_path.read_text() and "PRIVATE" not in status_path.read_text()
    recovery = tmp_path / "recovery"
    _, _, _, _, _, key_path, original_plan = approved_plan
    bundle.unseal(encrypted, key_path, recovery)
    assert (recovery / "plan.json").read_bytes() == original_plan
    assert (recovery / "publish-status.json").is_file() and not (recovery / "fresh").exists()
    assert capsys.readouterr() == ("", "")
    ordinary = tmp_path / "subsequent-coverage"
    ordinary.touch()
    assert ordinary.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize("publication_failure", [None, "upload"])
@pytest.mark.parametrize("status_failure", [None, "stage", "finish", "public-status"])
def test_archive_failure_retains_actual_publication_state_without_prepared_bytes(
        runner, approved_plan, publication_context, tmp_path, monkeypatch,
        publication_failure, status_failure):
    env, operator, outputs, reviewed = runner
    operator.fail = publication_failure
    original_seal = bundle.seal
    def seal(*args, **kwargs):
        if kwargs["success"]:
            raise bundle.InvalidBundle("archive-capacity")
        return original_seal(*args, **kwargs)
    monkeypatch.setattr(bundle, "seal", seal)
    original_json, original_status = app.write_json, prepare.public_status
    archive_writes = 0
    def write_json(path, value):
        nonlocal archive_writes
        if path.name == "publish-status.json" and value.get("stage") == "archive":
            archive_writes += 1
            if ((status_failure == "stage" and archive_writes == 1)
                    or (status_failure == "finish" and archive_writes == 2)):
                raise OSError("PRIVATE journal error")
        original_json(path, value)
    def public_status(path, value):
        if (status_failure == "public-status" and value.get("stage") == "archive"
                and "cleanup" not in value):
            raise OSError("PRIVATE public status error")
        original_status(path, value)
    monkeypatch.setattr(app, "write_json", write_json)
    monkeypatch.setattr(prepare, "public_status", public_status)
    assert driver.run(tmp_path) == 1
    private, encrypted, status_path = prepare.locations(env)
    status = json.loads(status_path.read_text())
    assert status["status"] == "BLOCKED" and status["stage"] == "archive"
    assert status["archive_error"] == "archive-capacity" and status["archive_ready"]
    assert status["changes"]["production"] == (
        "CONFIRMED" if publication_failure is None else "UNKNOWN")
    assert outputs.read_text() == "archive_ready=true\n" and not private.exists()
    assert "resume" not in operator.calls
    recovery = tmp_path / "recovery"
    key_path = approved_plan[5]
    handoff = bundle.unseal(encrypted, key_path, recovery)
    assert not handoff["prepared"] and handoff["plan_sha256"] is None
    assert handoff["publication"]["succeeded"] == (publication_failure is None)
    assert not (recovery / "plan.json").exists() and not (recovery / "prepared").exists()
    saved = json.loads((recovery / "publish-status.json").read_text())
    assert saved["authorization"]["reviewed_plan_sha256"] == reviewed
    assert saved["archive_failure"]["exception_type"] == "InvalidBundle"
    if status_failure:
        assert saved["archive_status_failure"]["exception_type"] == "OSError"
    if publication_failure:
        assert "failure" in saved
    assert "SECRET" not in status_path.read_text() and "PRIVATE" not in status_path.read_text()


@pytest.mark.parametrize("failure", ["digest", "snapshot", "prepared-bytes"])
def test_original_publish_gates_still_block_before_mutation(runner, tmp_path, monkeypatch, failure):
    env, operator, _, _ = runner
    if failure == "digest":
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text())
        event["inputs"]["reviewed_plan_sha256"] = "b" * 64
        Path(env["GITHUB_EVENT_PATH"]).write_text(json.dumps(event))
    elif failure == "snapshot":
        operator.state["rules_digest"] = "changed"
    else:
        original = driver.validate_handoff
        def tamper(store, *args):
            original(store, *args)
            (store / "prepared/feed-report.json").write_text("changed")
        monkeypatch.setattr(driver, "validate_handoff", tamper)
    assert driver.run(tmp_path) == 1
    assert not {"pause", "disable", "upload", "approve", "enable", "resume"} & set(operator.calls)


@pytest.mark.parametrize("failure", ["initial-status", "journal-status", "handoff", "seal",
                                      "output", "cleanup", "final-status"])
def test_finalization_always_attempts_cleanup_and_restores_umask(
        runner, tmp_path, monkeypatch, failure):
    env, _, outputs, _ = runner
    private, encrypted, status_path = prepare.locations(env)
    status_write, json_write = prepare.public_status, app.write_json
    def status(path, value):
        if ((failure == "initial-status" and value.get("stage") == "scope")
                or (failure == "journal-status" and value.get("status") == "RUNNING")
                or (failure == "final-status" and "cleanup" in value)):
            raise OSError("PRIVATE status error")
        status_write(path, value)
    def write_json(path, value):
        if failure == "handoff" and "publication" in value:
            raise OSError("PRIVATE handoff error")
        json_write(path, value)
    monkeypatch.setattr(prepare, "public_status", status)
    monkeypatch.setattr(app, "write_json", write_json)
    if failure == "seal":
        monkeypatch.setattr(bundle, "seal", lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("PRIVATE seal error")))
    elif failure == "output":
        outputs.unlink()
        outputs.mkdir()
    elif failure == "cleanup":
        original_cleanup = prepare.cleanup_store
        def cleanup(store, actual_env):
            original_cleanup(store, actual_env)
            raise OSError("PRIVATE cleanup error")
        monkeypatch.setattr(prepare, "cleanup_store", cleanup)
    try:
        result = driver.run(tmp_path)
    except OSError:
        assert failure in ("initial-status", "handoff", "output", "final-status")
    else:
        assert result == 1
    assert not private.exists() and not bundle.EVIDENCE_ROOT.exists()
    ordinary = tmp_path / "subsequent-coverage"
    ordinary.touch()
    assert ordinary.stat().st_mode & 0o777 == 0o644
    if failure == "seal":
        assert outputs.read_text() == "archive_ready=false\n" and not encrypted.exists()
    if status_path.exists():
        assert "PRIVATE" not in status_path.read_text()


def test_wrong_key_fails_without_publication(runner, tmp_path, monkeypatch):
    _, operator, outputs, _ = runner
    monkeypatch.setenv("SCHEMA431_ARCHIVE_KEY", base64.b64encode(os.urandom(32)).decode())
    assert driver.run(tmp_path) == 1
    assert not operator.calls and outputs.read_text() == "archive_ready=false\n"


def test_manual_publish_workflow_keeps_wif_and_explicit_inputs():
    workflow = (Path(__file__).resolve().parents[2]
                / ".github/workflows/static-app-release.yml").read_text()
    manual = workflow.split("\n  manual-publish:\n", 1)[1]
    condition = " ".join(manual.split("    if: >-\n", 1)[1]
                         .split("\n    runs-on:", 1)[0].split())
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "inputs.operation == 'publish-schema431'" in condition
    for name in ("prepare_run_id", "prepare_run_attempt", "reviewed_plan_sha256"):
        assert f"inputs.{name} != ''" in condition
        assert "${{ inputs." + name not in manual  # No shell interpolation of inputs.
    assert "environment: static-production" in manual
    assert "ref: " + bundle.TOOLING in manual and "ref: ${{ github.sha }}" in manual
    assert "create_credentials_file: false" in manual
    assert "https://www.googleapis.com/auth/firebase.readonly" in manual
    assert "secrets.CLOUDFLARE_PAGES_TOKEN" in manual and "release_automation.py" not in manual
    assert "SCHEMA431_EVIDENCE" not in manual
    assert "steps.publish-plan.outputs.archive_ready == 'true'" in manual
    assert "retention-days: 1" in manual and ".aesgcm" in manual


def test_report_does_not_claim_success_when_private_record_upload_failed(
        tmp_path, monkeypatch, capsys):
    env = {"RUNNER_TEMP": str(tmp_path), "GITHUB_RUN_ID": "345", "GITHUB_RUN_ATTEMPT": "1"}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    _, _, status_path = prepare.locations(env)
    prepare.public_status(status_path, {"status": "PUBLISHED", "stage": "resume"})
    monkeypatch.setenv("ARCHIVE_UPLOAD_OUTCOME", "failure")
    driver.report()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "BLOCKED" and result["stage"] == "archive-upload"
