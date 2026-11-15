"""Advisory records cannot replace original publication gates or disclose private inputs."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.static_ops import app_release as app
from scripts.static_ops import release_review as review
from scripts.static_ops import release_timing as timing
from tests.unit.test_static_app_release import NEW, OLD, SimulatedOperator

NOW = datetime(2026, 11, 15, 3, tzinfo=UTC)


@pytest.mark.parametrize(
    "plan_age,feed_age,plan_ok,feed_ok,remaining",
    [
        (10, 31, True, False, -60),
        (31, 10, False, True, -60),
        (30, 30, True, True, 0),
        (0, 0, True, True, 1800),
        (-1, 5, False, True, 1500),
        (5, -1, True, False, 1500),
    ],
)
def test_two_inclusive_windows_and_future_times(plan_age, feed_age, plan_ok, feed_ok, remaining):
    result = review.windows(
        (NOW - timedelta(minutes=plan_age)).isoformat(),
        (NOW - timedelta(minutes=feed_age)).isoformat(),
        NOW,
    )
    assert result["plan_within_window"] is plan_ok
    assert result["feed_within_window"] is feed_ok
    assert result["remaining_seconds"] == remaining
    assert result["sufficient_for_publication"] is False


@pytest.mark.parametrize(
    "value", [None, True, 42, "", "SECRET", "2026-11-15T03:00:00", "2026-11-31T03:00:00Z"]
)
@pytest.mark.parametrize("field", ["plan", "feed"])
def test_invalid_times_do_not_become_valid_windows(value, field):
    with pytest.raises((ValueError, TypeError)):
        review.windows(
            value if field == "plan" else NOW.isoformat(),
            value if field == "feed" else NOW.isoformat(),
            NOW,
        )


@pytest.fixture
def observed(tmp_path):
    store = tmp_path / "store"
    store.mkdir(mode=0o700)
    journal = app.Journal(store / "prepare-status.json", "prepare", NEW)
    op = SimulatedOperator(tmp_path)
    app.prepare(op, NEW, OLD, store, journal)
    journal.value.update(
        status="OK",
        reason="SECRET-EXCEPTION",
        rules_receipt={"private": "SECRET-RULES"},
        schema_receipt={"private": "SECRET-SCHEMA"},
    )
    journal.value["timings"][0]["raw"] = "SECRET-PROVIDER"
    archive = tmp_path / "encrypted.aesgcm"
    archive.write_bytes(b"synthetic encrypted bytes")
    value = review.create(
        store,
        journal.value,
        env={"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"},
        archive=archive,
    )
    path = tmp_path / "review.json"
    digest = review.save(path, value)
    return store, journal, path, digest, archive


def test_small_record_is_bound_to_original_bytes_and_excludes_private_details(observed):
    store, journal, path, digest, archive = observed
    value = review.load(path, digest, "123", "2", store=store, archive=archive)
    assert value["evidence"]["plan_sha256"] == review.file_hash(store / "plan.json")
    assert value["publication_authorized"] is False
    assert path.stat().st_size < 4096
    assert path.stat().st_mode & 0o777 == 0o600
    assert "SECRET" not in path.read_text()
    assert "rules_receipt" not in path.read_text()
    assert value["timings"][0]["status"] == "OK"


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "bytes",
        "run",
        "attempt",
        "digest",
        "archive",
        "plan",
        "catalog",
        "report",
        "release",
    ],
)
def test_missing_tampered_and_cross_run_records_fail(observed, change):
    store, _, path, digest, archive = observed
    run_id, attempt = "123", "2"
    if change == "missing":
        path.unlink()
    elif change == "bytes":
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "run":
        run_id = "456"
    elif change == "attempt":
        attempt = "3"
    elif change == "digest":
        digest = "f" * 64
    elif change == "archive":
        archive.write_bytes(b"changed")
    else:
        target = {
            "plan": store / "plan.json",
            "report": store / "prepared/feed-report.json",
            "catalog": store / "prepared/upload/dist-static/weather/msm/catalog.json",
            "release": store / "prepared/upload/dist-static/release.json",
        }[change]
        target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises((ValueError, OSError)):
        review.load(path, digest, run_id, attempt, store=store, archive=archive)


def test_unavailable_original_evidence_is_a_blocked_diagnostic(observed):
    store, journal, _, _, _ = observed
    (store / "plan.json").unlink()
    value = review.create(store, journal.value, env={})
    assert value["status"] == "BLOCKED" and value["evidence"] is None
    assert value["evidence_status"] == "UNAVAILABLE"
    assert "SECRET" not in json.dumps(value)


def test_local_common_finish_retains_plan_and_private_journal(observed, capsys):
    store, journal, _, _, _ = observed
    original = (store / "plan.json").read_bytes()
    journal.finish(True)
    result = json.loads(capsys.readouterr().out)
    value = review.load(
        store / "prepare-review.json", result["review_sha256"], None, None, store=store
    )
    assert value["windows"]["sufficient_for_publication"] is False
    assert (store / "plan.json").read_bytes() == original
    assert "SECRET-RULES" in journal.path.read_text()
    assert "SECRET" not in json.dumps(result)


def test_review_save_failure_does_not_report_success(observed, monkeypatch, capsys):
    _, journal, _, _, _ = observed

    def fail(*args):
        raise OSError("SECRET-DISK-ERROR")

    monkeypatch.setattr(review, "save", fail)
    with pytest.raises(app.Blocked, match="could not be saved"):
        journal.finish(True)
    assert json.loads(journal.path.read_text())["status"] == "BLOCKED"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "error,status",
    [(None, "OK"), (ValueError("SECRET"), "BLOCKED"), (KeyboardInterrupt(), "INTERRUPTED")],
)
def test_elapsed_time_and_failure_states_are_recorded(tmp_path, error, status):
    path = tmp_path / "timing.json"
    rows = []
    try:
        with timing.measure(rows, lambda: timing.write(path, rows), "msm-acquisition"):
            saved = json.loads(path.read_text())
            assert saved[0]["status"] == "RUNNING" and "seconds" not in saved[0]
            if error:
                raise error
    except BaseException as caught:
        assert caught is error
    result = json.loads(path.read_text())[0]
    assert result["status"] == status and result["seconds"] >= 0
    assert "SECRET" not in path.read_text()


def test_command_timing_records_failure_without_command_or_output(tmp_path):
    path = tmp_path / "command.json"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(timing.__file__)),
            "--file",
            str(path),
            "--phase",
            "static-build",
            sys.executable,
            "-c",
            'print("PRIVATE-COMMAND-OUTPUT"); raise SystemExit(7)',
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "PRIVATE-COMMAND-OUTPUT" in result.stdout  # host command() captures it privately
    assert "PRIVATE" not in path.read_text()
    assert json.loads(path.read_text())[0]["status"] == "BLOCKED"


def test_killed_measurement_stays_running_not_successful(tmp_path):
    path = tmp_path / "killed.json"
    code = """
import os, signal
from pathlib import Path
from scripts.static_ops import release_timing as t
rows=[]
p=Path(os.environ['TIMING_TEST_PATH'])
with t.measure(rows, lambda: t.write(p, rows), 'e2e'):
    os.kill(os.getpid(), signal.SIGKILL)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], env={**os.environ, "TIMING_TEST_PATH": str(path)}
    )
    assert result.returncode < 0
    assert json.loads(path.read_text())[0]["status"] == "RUNNING"


def test_timing_allowlist_rejects_names_and_nonfinite_durations():
    for row in [
        {"phase": "SECRET", "status": "OK"},
        {"phase": "e2e", "status": "SECRET"},
        {"phase": "e2e", "status": "OK", "seconds": float("nan")},
    ]:
        with pytest.raises(ValueError):
            timing.bounded([row])


@pytest.mark.parametrize(
    "conclusion,expected",
    [
        ("success", "OK"),
        ("failure", "BLOCKED"),
        ("cancelled", "INTERRUPTED"),
        ("skipped", "SKIPPED"),
        (None, "BLOCKED"),
    ],
)
def test_workflow_upload_and_dependencies_are_separate(conclusion, expected):
    steps = [
        {
            "name": name,
            "status": "completed",
            "conclusion": conclusion,
            "started_at": NOW.isoformat(),
            "completed_at": (NOW + timedelta(seconds=5)).isoformat(),
        }
        for name in [
            "Install the fixed reviewed tooling dependencies",
            "Retain only the authenticated encrypted result",
            "PRIVATE-PROVIDER",
        ]
    ]
    payload = {
        "total_count": 1,
        "jobs": [{"name": "manual-prepare", "run_id": 123, "steps": steps}],
    }
    rows = timing.workflow_rows(payload, "123", "manual-prepare")
    assert [r["phase"] for r in rows] == ["workflow-dependencies", "artifact-upload"]
    assert all(r["status"] == expected and r["seconds"] == 5 for r in rows)
    assert "PRIVATE" not in json.dumps(rows)
    with pytest.raises(ValueError):
        timing.workflow_rows(payload, "124", "manual-prepare")


def test_workflow_api_error_never_prints_provider_response(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("SECRET-API-RESPONSE")

    monkeypatch.setattr(timing.subprocess, "run", fail)
    assert timing.workflow_report(
        {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "publish"}
    ) == {"status": "UNAVAILABLE", "timings": []}


def test_window_overflow_retains_a_loadable_blocked_diagnostic(observed):
    store, journal, path, _, _ = observed
    plan_path = store / "plan.json"
    plan = json.loads(plan_path.read_text())
    plan["prepared_at"] = "9999-12-31T23:59:59+00:00"
    plan_path.write_text(json.dumps(plan))
    value = review.create(store, journal.value, env={})
    digest = review.save(path, value)
    loaded = review.load(path, digest, None, None)
    assert loaded["status"] == "BLOCKED" and loaded["evidence"] is None
    assert "windows" not in loaded


def test_common_main_captured_interrupt_keeps_publication_blocked_and_marks_timing(
    tmp_path, monkeypatch, capsys
):
    store = tmp_path / "interrupt-store"

    def interrupt(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(app.Operator, "snapshot", interrupt)
    monkeypatch.setattr(app, "command", lambda *a, **kw: str(tmp_path))
    monkeypatch.setattr(
        sys,
        "argv",
        ["app_release.py", "prepare", "--sha", NEW, "--current-sha", OLD, "--store", str(store)],
    )
    assert app.main() == 1
    journal = json.loads((store / "prepare-status.json").read_text())
    assert journal["status"] == "BLOCKED"
    assert journal["timings"][0]["status"] == "INTERRUPTED"
    assert journal["changes"]["production"] == "UNCHANGED"
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


def test_common_automation_captured_interrupt_retains_interrupt_kind(tmp_path, monkeypatch):
    from scripts.static_ops import release_automation as automation

    op = SimulatedOperator(tmp_path)

    def interrupt(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(op, "snapshot", interrupt)
    with pytest.raises(KeyboardInterrupt):
        automation.execute(op, NEW, OLD, tmp_path, phases=("prepare",))
    journal = json.loads((tmp_path / "prepare-status.json").read_text())
    assert journal["status"] == "BLOCKED"
    assert journal["timings"][0]["status"] == "INTERRUPTED"


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", "unknown", "success"])
@pytest.mark.parametrize("review_present", [False, True])
def test_common_report_keeps_delivery_failure_separate_from_publication(
    tmp_path, monkeypatch, capsys, outcome, review_present
):
    from scripts.static_ops import release_automation as automation

    app.write_json(
        tmp_path / "publish-status.json",
        {
            "mode": "publish",
            "sha": NEW,
            "status": "OK",
            "stage": "resume",
            "changes": {"production": "CONFIRMED"},
            "reason": "SECRET",
        },
    )
    # A different mode can upload successfully while this mode is missing.
    (tmp_path / "prepare-review.json").write_text("{}")
    if review_present:
        (tmp_path / "publish-review.json").write_text("{}")
    monkeypatch.setattr(automation, "release_store", lambda: tmp_path)
    monkeypatch.setenv("REVIEW_UPLOAD_OUTCOME", outcome)
    monkeypatch.setattr(sys, "argv", ["release_automation.py", "report"])
    monkeypatch.setattr(timing, "workflow_report", lambda _: {"status": "UNAVAILABLE"})
    assert automation.main() == 0
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == ("OK" if outcome == "success" and review_present else "BLOCKED")
    if value["status"] == "BLOCKED":
        assert value["stage"] == "review-upload" and value["operation_status"] == "OK"
    assert value["changes"]["production"] == "CONFIRMED"
    assert value["review_upload"] == outcome
    assert "SECRET" not in json.dumps(value)
