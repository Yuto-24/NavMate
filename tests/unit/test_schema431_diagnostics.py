"""Diagnostics observe the fixed command and keep private data out of public status."""

import json
import os
import subprocess
import sys

import pytest

from scripts.static_ops import app_release as app
from scripts.static_ops import schema431_bundle as bundle
from scripts.static_ops import schema431_diagnostics as diagnostics
from scripts.static_ops import schema431_prepare as driver


@pytest.fixture
def journal(tmp_path):
    store = tmp_path / "private"
    store.mkdir(mode=0o700)
    journal = driver.quiet_journal(app, store, tmp_path / "public.json")
    journal.stage("build-test")
    journal.finish(False)
    return journal


def command_arguments(kind, root, store, stage="prepared"):
    destination = store / stage
    image = "autonavlog-static-release:" + bundle.TOOLING
    if kind == "docker-build":
        return ["docker", "build", "-f", "scripts/static_ops/Dockerfile.build", "-t", image, "."]
    if kind == "msm-producer":
        return [sys.executable, str(root / "scripts/prepare_msm_feed.py"),
                "--output", str(destination / "feed"), "--cache", str(destination / "cache"),
                "--hours", "25", "--full-run"]
    if kind == "static-artifact-check":
        return ["node", str(root / "web/scripts/check-static.mjs"),
                str(destination / "upload/dist-static")]
    args = ["docker", "run", "--rm", "-i", "--mount",
            f"type=bind,source={destination / 'app'},target=/app", "--mount",
            f"type=bind,source={destination / 'feed'},target=/feed,readonly"]
    for name in app.gate.CONFIGURATION:
        args += ["--env", name]
    return args + ["--env", "AUTONAVLOG_MSM_FEED=/feed", "--env",
                   "AUTONAVLOG_REFERENCE_PYTHON=python3", "--env",
                   f"ARTIFACT_UID={os.getuid()}", "--env", f"ARTIFACT_GID={os.getgid()}",
                   image, "sh", "-eu", "-s"]


@pytest.mark.parametrize("kind", [
    "msm-producer", "docker-build", "candidate-build-tests", "static-artifact-check",
])
@pytest.mark.parametrize("stage", ["prepared", "fresh"])
def test_original_failed_command_is_observed_once_without_reexecution(
        journal, monkeypatch, capsys, kind, stage):
    args = command_arguments(kind, app.ROOT, journal.path.parent, stage)
    env = {name: "SECRET-PROVIDER-CREDENTIAL-" + str(i)
           for i, name in enumerate(diagnostics.SECRET_NAMES)}
    secrets = " ".join(env.values())
    calls = []
    original_command = app.command
    def run(actual_args, **kwargs):
        calls.append((actual_args, kwargs))
        return subprocess.CompletedProcess(actual_args, 7, "PRIVATE-OUT " + secrets,
                                           "PRIVATE-ERROR " + secrets)
    monkeypatch.setattr(app.subprocess, "run", run)
    with pytest.raises(app.Blocked) as failure:
        app.command(args, cwd=app.ROOT, env=env, input_text="PRIVATE-STDIN", timeout=123)
    diagnostics.record_failure(app, failure.value, app.ROOT, journal, env)
    assert app.command is original_command
    assert len(calls) == 1 and calls[0][0] is args
    assert calls[0][1]["env"] is env and calls[0][1]["input"] == "PRIVATE-STDIN"
    assert calls[0][1]["timeout"] == 123
    saved = json.loads(journal.path.read_text())["failure"]
    assert saved["command"] == {
        "kind": kind, "result": "completed", "returncode": 7,
        "stdout": {"tail": "PRIVATE-OUT [REDACTED] [REDACTED] [REDACTED]", "truncated": False},
        "stderr": {"tail": "PRIVATE-ERROR [REDACTED] [REDACTED] [REDACTED]", "truncated": False},
    }
    assert "PRIVATE-STDIN" not in journal.path.read_text()
    assert "SECRET" not in journal.path.read_text() and "GH_TOKEN" not in journal.path.read_text()
    assert journal.path.stat().st_mode & 0o777 == 0o600
    public = (journal.path.parent.parent / "public.json").read_text()
    assert "failure" not in public and "PRIVATE" not in public and "SECRET" not in public
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("change", [
    "provider", "docker-command", "docker-image", "docker-file", "docker-extra-env",
    "different-cwd", "producer-path", "producer-extra-arg", "different-store",
])
def test_provider_and_nonallowlisted_results_are_not_retained(journal, monkeypatch, change):
    args = command_arguments("docker-build", app.ROOT, journal.path.parent)
    cwd = app.ROOT
    if change == "provider":
        args = ["gh", "api", "repos/Yuto-24/NavMate/actions/variables"]
    elif change == "docker-command":
        args = ["docker", "login"]
    elif change == "docker-image":
        args[-2] = "other-image"
    elif change == "docker-file":
        args[3] = "OtherDockerfile"
    elif change == "docker-extra-env":
        args = command_arguments("candidate-build-tests", app.ROOT, journal.path.parent)
        args[2:2] = ["--env", "GH_TOKEN"]
    elif change == "different-cwd":
        cwd = journal.path.parent
    else:
        store = (journal.path.parent / "other"
                 if change == "different-store" else journal.path.parent)
        args = command_arguments("msm-producer", app.ROOT, store)
        if change == "producer-path":
            args[1] = "/other/prepare_msm_feed.py"
        if change == "producer-extra-arg":
            args += ["--other"]
    monkeypatch.setattr(app.subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess(a[0], 1, "PROVIDER-BODY", "PROVIDER-ERROR"))
    with pytest.raises(app.Blocked) as failure:
        app.command(args, cwd=cwd)
    diagnostics.record_failure(app, failure.value, app.ROOT, journal, {})
    saved = json.loads(journal.path.read_text())["failure"]
    assert "command" not in saved
    assert "PROVIDER" not in json.dumps(saved)


def test_only_the_trusted_command_frame_may_supply_a_result(journal):
    def other_command():
        args = command_arguments("docker-build", app.ROOT, journal.path.parent)
        result = subprocess.CompletedProcess(args, 1, "UNTRUSTED-RESULT", "UNTRUSTED-ERROR")
        assert result.returncode == 1
        raise app.Blocked("Fixed failure")
    with pytest.raises(app.Blocked) as failure:
        other_command()
    diagnostics.record_failure(app, failure.value, app.ROOT, journal, {})
    saved = json.loads(journal.path.read_text())["failure"]
    assert "command" not in saved and "UNTRUSTED" not in json.dumps(saved)


@pytest.mark.parametrize("cause,expected", [("timeout", "timeout"), ("os", "spawn-error")])
def test_missing_completed_process_has_an_explicit_classification(journal, monkeypatch, cause,
                                                                 expected):
    args = command_arguments("docker-build", app.ROOT, journal.path.parent)
    def run(*a, **kw):
        if cause == "timeout":
            raise subprocess.TimeoutExpired(a[0], 30, output=b"PRIVATE-PARTIAL-OUTPUT")
        raise OSError("PRIVATE-NATIVE-MESSAGE")
    monkeypatch.setattr(app.subprocess, "run", run)
    with pytest.raises(app.Blocked) as failure:
        app.command(args, cwd=app.ROOT)
    diagnostics.record_failure(app, failure.value, app.ROOT, journal, {})
    saved = json.loads(journal.path.read_text())["failure"]
    assert saved["command"] == {"kind": "docker-build", "result": expected}
    assert "PRIVATE" not in json.dumps(saved)


def test_tail_redacts_before_the_byte_boundary_and_handles_invalid_utf8():
    secret = "SENSITIVE-CREDENTIAL-THAT-CROSSES-THE-BOUNDARY"
    result = diagnostics.private_tail(("あ" * 100 + secret + "-end").encode(),
                                      {"GH_TOKEN": secret}, 20)
    assert result["truncated"] and len(result["tail"].encode()) <= 20
    assert "[REDACTED]-end" in result["tail"] and "BOUNDARY" not in result["tail"]
    assert diagnostics.private_tail(b"\xffvalid", {})["tail"].endswith("valid")
    overlapping = {"GH_TOKEN": "short-secret", "CLOUDFLARE_API_TOKEN": "short-secret-longer"}
    assert diagnostics.private_tail("short-secret-longer short-secret", overlapping)["tail"] == (
        "[REDACTED] [REDACTED]")


def test_journal_budget_omits_output_before_discarding_failure_metadata(journal, monkeypatch):
    args = command_arguments("docker-build", app.ROOT, journal.path.parent)
    monkeypatch.setattr(app.subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess(a[0], 7, "x" * 16000, "y" * 16000))
    monkeypatch.setattr(bundle, "MAX_RECORD", len(journal.path.read_bytes()) + 2048)
    with pytest.raises(app.Blocked) as failure:
        app.command(args, cwd=app.ROOT)
    diagnostics.record_failure(app, failure.value, app.ROOT, journal, {})
    saved = json.loads(journal.path.read_text())["failure"]
    assert saved["command"] == {"kind": "docker-build", "result": "completed", "returncode": 7}
    assert saved["output_omitted"] == "journal-size-limit"
    assert len(journal.path.read_bytes()) <= bundle.MAX_RECORD


def test_native_error_messages_and_general_frame_locals_are_not_saved(journal):
    private_variable = "PROVIDER-RESPONSE-BODY"
    with pytest.raises(ValueError) as failure:
        raise ValueError(private_variable)
    diagnostics.record_failure(app, failure.value, app.ROOT, journal, {})
    saved = json.loads(journal.path.read_text())["failure"]
    assert saved["exception_type"] == "ValueError" and saved["stack"]
    assert private_variable not in json.dumps(saved) and "message" not in saved


@pytest.mark.parametrize("problem", ["extraction", "write", "size"])
def test_diagnostics_cannot_break_the_existing_failure_journal(journal, monkeypatch, problem):
    original = journal.path.read_bytes()
    with pytest.raises(app.Blocked) as failure:
        raise app.Blocked("Fixed failure")
    if problem == "extraction":
        monkeypatch.setattr(diagnostics, "private_tail", lambda *a, **kw: 1 / 0)
    elif problem == "write":
        monkeypatch.setattr(journal, "save", lambda: 1 / 0)
    else:
        monkeypatch.setattr(bundle, "MAX_RECORD", len(original))
    diagnostics.record_failure(app, failure.value, app.ROOT, journal, {})
    assert journal.path.read_bytes() == original and "failure" not in journal.value


@pytest.mark.parametrize("error,expected", [
    (bundle.InvalidBundle("archive-capacity"), "archive-capacity"),
    (bundle.InvalidBundle("upload-symlink"), "upload-symlink"),
    (bundle.InvalidBundle("PRIVATE arbitrary text"), "archive-failed"),
    (OSError("archive-capacity"), "archive-failed"),
    (PermissionError("PRIVATE path"), "archive-failed"),
])
def test_public_archive_errors_are_fixed_codes_only(error, expected):
    assert diagnostics.archive_error_code(error) == expected


def test_archive_diagnostics_preserve_original_failure(journal):
    original = {"exception_type": "Blocked", "stage": "build-test"}
    journal.value["failure"] = original
    journal.save()
    with pytest.raises(OSError) as error:
        raise OSError("PRIVATE archive path")
    diagnostics.record_failure(app, error.value, app.ROOT, journal, {}, entry="archive_failure")
    saved = json.loads(journal.path.read_text())
    assert saved["failure"] == original
    assert saved["archive_failure"]["exception_type"] == "OSError"
    assert saved["archive_failure"]["stage"] == "build-test"
    assert "PRIVATE" not in json.dumps(saved)
