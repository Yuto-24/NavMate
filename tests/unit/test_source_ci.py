"""Offline Actions evidence and promotion gates; no production failure injection."""

import copy
import hashlib
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.static_ops import source_ci as ci

SHA = "a" * 40
OK = {"status": "completed", "conclusion": "success"}


@pytest.fixture
def evidence():
    run = {**OK, "id": 42, "head_sha": SHA, "run_attempt": 2, "event": "push",
           "head_branch": "main", "head_repository": {"full_name": ci.REPO},
           "path": ci.WORKFLOW}
    jobs = [{**OK, "name": name, "steps": [{**OK, "name": step} for step in ci.WEB_STEPS]}
            for name in sorted(ci.REQUIRED)]
    return {"run": run, "jobs": jobs}


def reader(evidence):
    def get(path):
        if path.startswith("actions/workflows/test.yml/runs?"):
            assert f"head_sha={SHA}&event=push" in path
            return {"workflow_runs": [evidence["run"]]}
        assert path.startswith("actions/runs/42/attempts/2/jobs?")
        return {"jobs": evidence["jobs"], "total_count": len(evidence["jobs"])}
    return get


def test_full_push_run_and_executed_source_suites(evidence):
    assert ci.require_success(reader(evidence), SHA) == {"sha": SHA, "run_id": 42, "run_attempt": 2}


@pytest.mark.parametrize("field,value", [
    ("status", "in_progress"), ("conclusion", "failure"), ("conclusion", "cancelled"),
    ("conclusion", "skipped"), ("event", "pull_request"), ("head_sha", "b" * 40),
    ("head_repository", {"full_name": "fork/NavMate"}), ("head_branch", "feature"),
    ("path", ".github/workflows/other.yml"), ("run_attempt", None),
])
def test_non_success_foreign_pr_and_wrong_source_rejected(evidence, field, value):
    evidence["run"][field] = value
    with pytest.raises(ci.Unavailable):
        ci.require_success(reader(evidence), SHA)


@pytest.mark.parametrize("name", sorted(ci.REQUIRED))
@pytest.mark.parametrize("state", ["missing", "failure", "cancelled", "skipped"])
def test_green_aggregate_never_covers_missing_or_skipped_suites(evidence, name, state):
    if state == "missing":
        evidence["jobs"] = [job for job in evidence["jobs"] if job["name"] != name]
    else:
        next(job for job in evidence["jobs"] if job["name"] == name)["conclusion"] = state
    with pytest.raises(ci.Unavailable):
        ci.require_success(reader(evidence), SHA)


@pytest.mark.parametrize("name", sorted(ci.WEB_STEPS))
def test_skipped_step_inside_successful_web_job_is_not_reusable(evidence, name):
    web = next(job for job in evidence["jobs"] if job["name"] == "web")
    next(step for step in web["steps"] if step["name"] == name)["conclusion"] = "skipped"
    with pytest.raises(ci.Unavailable):
        ci.require_success(reader(evidence), SHA)


def test_newer_failure_is_not_hidden_by_older_success(evidence):
    newer = {**evidence["run"], "id": 43, "conclusion": "failure"}
    with pytest.raises(ci.Unavailable):
        ci.require_success(lambda _: {"workflow_runs": [newer, evidence["run"]]}, SHA)


def test_job_pagination_and_latest_attempt(evidence):
    base = reader(evidence)
    calls = []

    def get(path):
        calls.append(path)
        if "jobs?" not in path:
            return base(path)
        return {"total_count": len(evidence["jobs"]),
                "jobs": evidence["jobs"][:2] if path.endswith("page=1") else evidence["jobs"][2:]}

    ci.require_success(get, SHA)
    assert calls[-1].endswith("attempts/2/jobs?per_page=100&page=2")


def test_provider_errors_do_not_leak_response_or_credentials():
    def get(_):
        raise OSError("TOKEN_CANARY signed URL")
    with pytest.raises(ci.Unavailable, match="^Source CI evidence unavailable$"):
        ci.require_success(get, SHA)


@pytest.fixture
def artifact(tmp_path):
    for file in (ci.WORKFLOW, ci.INVENTORY_SCRIPT):
        path = tmp_path / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file)
    value = {"sha": SHA, "run_id": "42", "run_attempt": "2",
             "workflow": hashlib.sha256((tmp_path / ci.WORKFLOW).read_bytes()).hexdigest(),
             "producer": hashlib.sha256((tmp_path / ci.INVENTORY_SCRIPT).read_bytes()).hexdigest()}
    return tmp_path, value


def bundle(value, *, name="source-ci-web.json"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, json.dumps(value))
    raw = output.getvalue()
    return raw, {"id": 99, "name": "source-ci-web-2", "expired": False,
                 "workflow_run": {"head_sha": SHA},
                 "digest": "sha256:" + hashlib.sha256(raw).hexdigest()}


@pytest.mark.parametrize("damage", [None, "sha", "run_id", "run_attempt", "workflow", "producer",
                                    "digest", "expired", "path", "download", "head_sha"])
def test_only_matching_inventory_can_authorize_reuse(artifact, damage):
    root, value = artifact
    expected = copy.deepcopy(value)
    if damage in value:
        value[damage] = "mismatch"
    raw, meta = bundle(value, name=("../source-ci-web.json" if damage == "path"
                                    else "source-ci-web.json"))
    if damage == "expired":
        meta["expired"] = True
    if damage == "digest":
        meta["digest"] = "sha256:bad"
    if damage == "head_sha":
        meta["workflow_run"]["head_sha"] = "b" * 40

    def download(_):
        if damage == "download":
            raise OSError("unavailable")
        return raw

    result = ci.web_inventory(lambda _: {"artifacts": [meta], "total_count": 1}, download,
                              {"sha": SHA, "run_id": 42, "run_attempt": 2}, root)
    assert result == (expected if damage is None else None)


def test_unattended_static_ci_wait_precedes_pause_and_build(monkeypatch, tmp_path):
    from scripts.static_ops import app_release as app
    from scripts.static_ops import release_automation as auto

    operator = auto.ActionsOperator({}, tmp_path)
    writes = []
    operator.gh = lambda _: {"workflow_runs": []}
    monkeypatch.setattr(app.Operator, "snapshot", lambda *a, **k: writes.append("snapshot"))
    with pytest.raises(app.Blocked, match="push run missing"):
        operator.snapshot(SHA, "b" * 40)
    assert writes == []
    assert app.Operator(tmp_path).source_evidence({}) is None


@pytest.mark.parametrize("reused", [True, False])
def test_build_executes_reuse_or_fallback_without_losing_artifact_gates(tmp_path, reused):
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/static_ops/build_app_release.sh").read_text()
    # Execute the production shell with tool doubles, never provider operations.
    # Timing still calls the real sequence; only expensive child commands are replaced.
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "commands.log"
    for program, body in {
        "git": "exit 0",
        "chown": "exit 0",
        "curl": "exit 0",
        "node": "exit " + ("0" if reused else "1"),
        "npm": 'echo "npm $*" >> "$COMMAND_LOG"',
        "python": '''if [ "$1" = /release_timing.py ]; then
  shift 5
  "$@"
elif [ "$1" = -m ] && [ "$2" = http.server ]; then
  sleep 10
else
  echo "python $*" >> "$COMMAND_LOG"
fi''',
    }.items():
        path = commands / program
        path.write_text("#!/bin/sh\nset -eu\n" + body + "\n")
        path.chmod(0o755)
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor/jma_gpv_weather-fixture.whl").touch()
    subprocess.run(["sh", "-eu", "-s"], input=script, text=True, cwd=tmp_path,
                   env={**os.environ, "PATH": str(commands) + os.pathsep + os.environ["PATH"],
                        "ARTIFACT_UID": "1", "ARTIFACT_GID": "1", "COMMAND_LOG": str(log)},
                   check=True, timeout=15)
    executed = log.read_text()
    assert ("npm --prefix web run typecheck" in executed) is not reused
    assert ("npm --prefix web run test:static-artifact" in executed) is not reused
    for command in ("npm --prefix web run build:static", "npm --prefix web run test:static",
                    "python scripts/export_schemas.py --check",
                    "python scripts/validate_release.py",
                    "python scripts/validate_runtime_data.py data"):
        assert command in executed
