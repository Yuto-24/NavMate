"""Local evidence reapplication never grants publication or changes old evidence."""

import json
import os
from types import SimpleNamespace

import pytest

from scripts.static_ops import app_release as app
from scripts.static_ops import schema431_bundle as bundle
from scripts.static_ops import schema431_reapply232 as reapply


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    source = tmp_path / "original"
    source.mkdir(mode=0o700)
    monkeypatch.setattr(reapply, "PREVIOUS_ROOT", source)
    monkeypatch.setattr(reapply, "DESTINATION", tmp_path / "new")
    identity = {"sha": reapply.PREVIOUS, "current_sha": reapply.CURRENT,
                "tooling_sha": reapply.TOOLING, "project": "PRIVATE-PROJECT"}
    original = {**identity, "checks": {}}
    for role in bundle.ROLES:
        report = {"identity": identity, "check": role, "result": "PASS",
                  "reviewed_by": "original-reviewer", "summary": "original observation",
                  "observations": ["preserved-test-result"], "limits": ["original-limit"]}
        name = role + ".json"
        raw = json.dumps(report, indent=3).encode() + b"\r\n"
        bundle.write_private(source / name, raw)
        original["checks"][role] = {
            "result": "PASS", "reviewed_by": report["reviewed_by"], "summary": report["summary"],
            "record": {"path": name, "sha256": bundle.sha256(raw)},
        }
    raw = json.dumps(original, indent=3).encode() + b"\r\n"
    bundle.write_private(source / bundle.RECORD_NAME, raw)
    monkeypatch.setattr(reapply, "PREVIOUS_RECORD_SHA256", bundle.sha256(raw))
    record, reports = reapply.original_evidence()
    calls = []

    def reviewed_schema(candidate, current, variables):
        calls.append(candidate)
        record = json.loads(operator.schema_transition.read_bytes())
        assert record["sha"] == candidate and record["current_sha"] == current
        return {"record": record, "sha256": bundle.sha256(operator.schema_transition.read_bytes()),
                "evidence": {role: {"sha256": check["record"]["sha256"]}
                             for role, check in record["checks"].items()}}

    operator = SimpleNamespace(reviewed_schema=reviewed_schema)
    return source, record, reports, operator, calls


def test_separate_record_preserves_observations_limits_and_original_bytes(evidence):
    source, record, reports, operator, calls = evidence
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    digest = reapply.write_reapplication(operator, {}, record, reports, {"basis": "reviewed"})
    assert calls == [reapply.PREVIOUS, reapply.CANDIDATE]
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    new_record = json.loads((reapply.DESTINATION / bundle.RECORD_NAME).read_bytes())
    assert digest == bundle.sha256((reapply.DESTINATION / bundle.RECORD_NAME).read_bytes())
    assert new_record["sha"] == reapply.CANDIDATE
    for role in bundle.ROLES:
        report = json.loads((reapply.DESTINATION / (role + ".json")).read_bytes())
        assert report["source_report"] == json.loads(reports[role])
        assert report["source_report_sha256"] == bundle.sha256(reports[role])
        assert report["source_record_sha256"] == reapply.PREVIOUS_RECORD_SHA256
        assert report["identity"]["sha"] == reapply.CANDIDATE
        assert "applicability review" in report["reviewed_by"]
        assert "No new experiment is claimed" in report["summary"]
    assert reapply.DESTINATION.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in reapply.DESTINATION.iterdir())


@pytest.mark.parametrize("failure", ["record", "report", "permissions", "symlink"])
def test_untrusted_original_files_are_rejected(evidence, failure):
    source, _, _, _, _ = evidence
    record = source / bundle.RECORD_NAME
    report = source / (bundle.ROLES[0] + ".json")
    if failure in ("record", "report"):
        path = record if failure == "record" else report
        path.write_bytes(path.read_bytes() + b" ")
    elif failure == "permissions":
        report.chmod(0o644)
    else:
        moved = source / "report-backup.json"
        report.rename(moved)
        report.symlink_to(moved)
    with pytest.raises(bundle.InvalidBundle):
        reapply.original_evidence()
    assert not reapply.DESTINATION.exists()


@pytest.mark.parametrize("candidate", [reapply.PREVIOUS, reapply.CANDIDATE])
def test_either_fixed_validator_failure_leaves_no_new_record(evidence, candidate):
    source, record, reports, operator, _ = evidence
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    accepted = operator.reviewed_schema

    def reject(sha, *args):
        if sha == candidate:
            raise app.Blocked("validator rejection")
        return accepted(sha, *args)

    operator.reviewed_schema = reject
    with pytest.raises(app.Blocked):
        reapply.write_reapplication(operator, {}, record, reports, {})
    assert not reapply.DESTINATION.exists()
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}


def test_existing_destination_is_not_overwritten(evidence):
    _, record, reports, operator, _ = evidence
    reapply.DESTINATION.mkdir()
    retained = reapply.DESTINATION / "retained"
    retained.write_text("preserve")
    with pytest.raises(FileExistsError):
        reapply.write_reapplication(operator, {}, record, reports, {})
    assert retained.read_text() == "preserve"


def test_expanded_report_limit_is_checked_before_writing(evidence, monkeypatch):
    _, record, reports, operator, _ = evidence
    monkeypatch.setattr(bundle, "MAX_REPORT", 10)
    with pytest.raises(bundle.InvalidBundle, match="new-report-size"):
        reapply.write_reapplication(operator, {}, record, reports, {})
    assert not reapply.DESTINATION.exists()


@pytest.mark.parametrize("difference", ["runtime", "version", "tag", "tooling"])
def test_source_review_rejects_unreviewed_difference(difference):
    def git(*args):
        if args == ("rev-parse", "HEAD"):
            return "0" * 40 if difference == "tooling" else reapply.TOOLING
        if args[0] == "diff":
            return "\n".join(sorted((*reapply.CHANGED_PATHS,
                                    *(('web/src/project.ts',) if difference == "runtime" else ()))))
        if args[0] == "show":
            return "0.0.0" if difference == "version" else (
                "2.3.1" if args[1].startswith(reapply.PREVIOUS) else "2.3.2")
        if args[1].startswith("v"):
            return "0" * 40 if difference == "tag" else (
                reapply.PREVIOUS if args[1].startswith("v2.3.1") else reapply.CANDIDATE)
        return "tree"

    with pytest.raises(bundle.InvalidBundle):
        reapply.check_sources(SimpleNamespace(git=git))


@pytest.mark.parametrize("field,value", [("head_sha", reapply.PREVIOUS),
    ("status", "in_progress"), ("conclusion", "failure"),
    ("path", ".github/workflows/other.yml"), ("repository", {"id": 1})])
def test_candidate_ci_must_match_exact_successful_run(field, value):
    run = {"head_sha": reapply.CANDIDATE, "status": "completed", "conclusion": "success",
           "path": ".github/workflows/test.yml", "repository": {"id": reapply.driver.REPO_ID}}
    run[field] = value

    def gh(endpoint):
        if endpoint == "releases/tags/v2.3.2":
            return {"tag_name": "v2.3.2", "draft": False, "prerelease": False,
                    "published_at": "2026-11-13T07:09:12Z"}
        assert endpoint == "actions/runs/43383649255"
        return run

    with pytest.raises(bundle.InvalidBundle):
        reapply.check_release(SimpleNamespace(gh=gh))


def test_reader_never_mutates_github(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(app.Operator, "gh", lambda *args: calls.append(args))
    reader = reapply.read_only_operator(app, tmp_path)
    with pytest.raises(bundle.InvalidBundle, match="github-read-only"):
        reader.gh("actions/variables/STATIC_AUTOMATION_ENABLED", "PATCH", {"value": "false"})
    assert calls == []


def test_failure_hides_private_details_and_restores_umask(tmp_path, monkeypatch, capsys):
    def failed(_):
        raise RuntimeError("PRIVATE-PROVIDER-RESPONSE")

    monkeypatch.setattr(reapply.driver, "load_tooling", failed)
    previous = os.umask(0o022)
    try:
        assert reapply.main(["--tooling", str(tmp_path)]) == 1
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(previous)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "BLOCKED", "stage": "tooling"}
    assert captured.err == ""
