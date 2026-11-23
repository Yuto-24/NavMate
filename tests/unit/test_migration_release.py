"""Fail-closed GitHub migration review, transport and publication boundaries."""

import copy
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
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


@pytest.fixture
def reviews(monkeypatch):
    repository = {
        "id": 10,
        "private": True,
        "full_name": "Yuto-24/private-review",
        "owner": {"id": 65487096},
    }
    records = {}

    def api(self, path, method="GET", body=None):
        if not path:
            return copy.deepcopy(repository)
        if method == "POST":
            if path == "issues":
                result = {"number": 1, "body": body["body"], "state": "open"}
                records["issues/1"] = result
            else:
                result = {
                    "id": 2,
                    "body": body["body"],
                    "issue_url": "https://api.github.com/repos/Yuto-24/private-review/issues/1",
                }
                records["issues/comments/2"] = result
            return result
        return copy.deepcopy(records[path])

    monkeypatch.setenv("STATIC_MIGRATION_REVIEW_REPOSITORY", repository["full_name"])
    monkeypatch.setenv("STATIC_MIGRATION_REVIEW_TOKEN", "test-only")
    monkeypatch.setattr(review.Reviews, "api", api)
    return review.Reviews(None), repository, records


def test_private_read_binds_visible_summary_and_full_observation(reviews):
    store, _, records = reviews
    value = review.signed_evidence(evidence(), KEY)
    reference = store.save(value)
    assert store.read("1", reference["sha256"]) == value
    review.verify_evidence(value, KEY)
    assert "Tests are not approval" in records["issues/1"]["body"]
    records["issues/1"]["body"] = records["issues/1"]["body"].replace(
        "Tests are not approval", "Tests authorize publication"
    )
    with pytest.raises(app.Blocked, match="changed"):
        store.read("1", reference["sha256"])


@pytest.mark.parametrize("change", ["public", "owner", "repository", "withdrawn", "expired"])
def test_review_identity_privacy_withdrawal_and_expiry_fail_closed(reviews, change):
    store, repository, records = reviews
    value = evidence()
    if change == "expired":
        value["created_at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    reference = store.save(value)
    if change == "public":
        repository["private"] = False
    elif change == "owner":
        repository["owner"]["id"] = 20
    elif change == "repository":
        repository["id"] = 11
    elif change == "withdrawn":
        records["issues/1"]["state"] = "closed"
    with pytest.raises(app.Blocked):
        store.read("1", reference["sha256"])


def test_prepared_comment_cannot_be_moved_to_another_issue(reviews):
    store, _, records = reviews
    store.save(evidence())
    value = {**evidence(), "phase": "prepared", "issue": 1}
    reference = store.save(value, issue=1)
    assert store.read("2", reference["sha256"], comment=True) == value
    records["issues/comments/2"]["issue_url"] += "2"
    with pytest.raises(app.Blocked, match="another Issue"):
        store.read("2", reference["sha256"], comment=True)


def test_modified_observations_cannot_be_resigned_by_digest_or_review():
    value = review.signed_evidence(evidence(), KEY)
    value["checks"]["old_to_new"]["observations"]["receipt"] = 2
    with pytest.raises(app.Blocked, match="sealed"):
        review.verify_evidence(value, KEY)


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
    for phase in ("prepare", "publish"):
        job = workflow.split("\n  migration-" + phase + ":", 1)[1].split("\n  migration-", 1)[0]
        assert "inputs.operation == '" + phase + "-migration'" in job
        assert "github.ref == 'refs/heads/main'" in job
        assert "group: static-production" in job
        assert "queue: max" in job
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
