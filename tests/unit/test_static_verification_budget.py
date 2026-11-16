"""Regression coverage for MSM verification budgets and retained payload diagnostics."""

import hashlib
import importlib.util
import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).parents[2] / "scripts/static_ops"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def poll(monkeypatch):
    module = load_script("wait_for_candidate")
    clock = SimpleNamespace(now=0, sleeps=[], calls=[])

    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    return module, clock


def test_complete_pass_can_outlast_short_poll_budget(poll, monkeypatch, capsys):
    module, clock = poll

    def run(command, **kwargs):
        clock.calls.append((command, kwargs["timeout"]))
        # First response is the old release; the next complete pass takes 55 seconds.
        duration = 1 if len(clock.calls) == 1 else 55
        clock.now += min(duration, kwargs["timeout"])
        if duration > kwargs["timeout"]:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        code = 1 if len(clock.calls) == 1 else 0
        return subprocess.CompletedProcess(command, code, '{"status":"OK"}\n', "old release")

    monkeypatch.setattr(module.subprocess, "run", run)
    module.wait_for_candidate(Path("release.json"), verify_payloads=True)
    assert [budget for _, budget in clock.calls] == [300, 289]
    assert clock.now == 66
    assert clock.sleeps == [10]
    assert all("--verify-payloads" in command for command, _ in clock.calls)
    assert capsys.readouterr().out.count('"status":"OK"') == 1


@pytest.mark.parametrize("verify_payloads, expected_budget", [(False, 30), (True, 300)])
def test_complete_and_metadata_checks_use_separate_budgets(
    poll, monkeypatch, verify_payloads, expected_budget
):
    module, clock = poll

    def run(command, **kwargs):
        clock.calls.append(kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", run)
    module.wait_for_candidate(Path("release.json"), verify_payloads=verify_payloads)
    assert clock.calls == [expected_budget]


@pytest.mark.parametrize("returncode", [1, 2])
def test_complete_failures_remain_retryable_or_fatal(poll, monkeypatch, capsys, returncode):
    module, clock = poll

    def run(command, **kwargs):
        clock.calls.append(kwargs["timeout"])
        return subprocess.CompletedProcess(command, returncode, "", "validation failed")

    monkeypatch.setattr(module.subprocess, "run", run)
    if returncode == 2:
        with pytest.raises(RuntimeError, match="stopped after 1 attempt"):
            module.wait_for_candidate(Path("release.json"), verify_payloads=True, timeout=25)
        assert clock.calls == [25]
        assert clock.sleeps == []
    else:
        with pytest.raises(TimeoutError, match=r"25s \(3 attempt"):
            module.wait_for_candidate(Path("release.json"), verify_payloads=True, timeout=25)
        assert clock.calls == [25, 15, 5]
        assert clock.sleeps == [10, 10, 5]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("result", ["timeout", "success_at_deadline"])
def test_complete_pass_cannot_escape_total_deadline(poll, monkeypatch, capsys, result):
    module, clock = poll

    def run(command, **kwargs):
        clock.calls.append(kwargs["timeout"])
        clock.now += kwargs["timeout"]
        if result == "timeout":
            raise subprocess.TimeoutExpired(
                command, kwargs["timeout"], stderr=b"target=asset.npz\n"
            )
        return subprocess.CompletedProcess(command, 0, "must not be printed", "")

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(TimeoutError, match="45s") as error:
        module.wait_for_candidate(Path("release.json"), verify_payloads=True, timeout=45)
    assert clock.calls == [45]
    assert clock.sleeps == []
    assert capsys.readouterr().out == ""
    if result == "timeout":
        assert "target=asset.npz" in str(error.value)


def test_real_complete_checker_outlasts_attempt_budget(tmp_path, monkeypatch, capsys):
    module = load_script("wait_for_candidate")
    (tmp_path / "check_candidate.py").write_text(
        'import time\ntime.sleep(0.15)\nprint("complete")\n'
    )
    monkeypatch.setattr(module, "__file__", str(tmp_path / "wait_for_candidate.py"))
    module.wait_for_candidate(
        Path("unused"), verify_payloads=True, timeout=2, interval=0.01, attempt_timeout=0.05,
    )
    output = capsys.readouterr()
    assert output.out == "complete\n"
    assert "verified after 1 attempt(s)" in output.err


def test_hung_complete_checker_is_killed_at_total_deadline(tmp_path, monkeypatch):
    module = load_script("wait_for_candidate")
    (tmp_path / "check_candidate.py").write_text("import time\ntime.sleep(60)\n")
    monkeypatch.setattr(module, "__file__", str(tmp_path / "wait_for_candidate.py"))
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        module.wait_for_candidate(
            Path("unused"), verify_payloads=True, timeout=0.2, interval=0.01, attempt_timeout=0.05,
        )
    assert time.monotonic() - start < 5


@pytest.fixture
def retained(monkeypatch):
    module = load_script("operations")
    now = datetime(2026, 11, 17, tzinfo=UTC)
    payload = b"expected forecast"
    digest = hashlib.sha256(payload).hexdigest()
    asset = {"file": digest + ".npz", "bytes": len(payload), "sha256": digest,
             "run": "20261116090000"}
    state = SimpleNamespace(ops=module, now=now, asset=asset, payload=payload, calls=[])

    def fetch(url, limit=25 * 1024**2):
        state.calls.append(url)
        if url.endswith("catalog.json"):
            return json.dumps({"schema_version": 1, "assets": [state.asset]}).encode()
        return state.payload

    monkeypatch.setattr(module, "fetch", fetch)
    return state


@pytest.mark.parametrize("received", [b"short", b"x" * len(b"expected forecast")])
def test_restore_mismatch_reports_sizes_hashes_and_target(retained, tmp_path, received):
    state = retained
    state.payload = received
    with pytest.raises(ValueError, match="Retained payload integrity failure") as error:
        state.ops.restore("https://example.com", tmp_path, state.now)
    evidence = json.loads(str(error.value).split(": ", 1)[1])
    assert evidence == {
        "target": "weather/msm/" + state.asset["file"],
        "run": state.asset["run"],
        "expected": {"bytes": state.asset["bytes"], "sha256": state.asset["sha256"]},
        "observed": {"bytes": len(received), "sha256": hashlib.sha256(received).hexdigest()},
    }
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("field, value", [("bytes", "SECRET"), ("sha256", "SECRET"),
                                         ("sha256", {"token": "SECRET"})])
def test_restore_diagnostics_do_not_echo_unvalidated_metadata(retained, tmp_path, field, value):
    state = retained
    state.asset[field] = value
    with pytest.raises(ValueError, match="Retained payload integrity failure") as error:
        state.ops.restore("https://example.com", tmp_path, state.now)
    assert "SECRET" not in str(error.value)
    evidence = json.loads(str(error.value).split(": ", 1)[1])
    assert evidence["expected"][field] == "invalid"
    assert list(tmp_path.iterdir()) == []


def test_valid_retained_payload_is_preserved(retained, tmp_path):
    state = retained
    result = state.ops.restore("https://example.com", tmp_path, state.now)
    assert result == {"retained_assets": 1}
    assert (tmp_path / state.asset["file"]).read_bytes() == state.payload
    assert json.loads((tmp_path / "catalog.json").read_bytes())["assets"] == [state.asset]


def test_expired_retention_is_not_downloaded(retained, tmp_path):
    state = retained
    state.asset["run"] = (state.now - timedelta(days=8)).strftime("%Y%m%d%H%M%S")
    assert state.ops.restore("https://example.com", tmp_path, state.now) == {"retained_assets": 0}
    assert len(state.calls) == 1
