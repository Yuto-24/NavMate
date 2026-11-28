"""Evidence lifecycle contracts run against memory snapshots and the real emulator."""

import contextlib
import copy
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest
import yaml

from scripts.static_ops import app_release as app
from scripts.static_ops import migration_firestore as fs
from scripts.static_ops import migration_release as migration
from scripts.static_ops import migration_review as review

KEY = b"k" * 32
CANARY = "PRIVATE_CANARY_config_sample_exception_514"


def isolation_transport(monkeypatch, callback):
    database = fs.Firestore.__new__(fs.Firestore)
    database.credentials = object()
    monkeypatch.setattr(database, "authorization", lambda: "Bearer synthetic-test")

    def opener(handler):
        assert isinstance(handler, fs.NoRedirect)
        result = handler.redirect_request(None, None, 302, None, None, "https://example.invalid")
        assert result is None
        return SimpleNamespace(open=callback)

    monkeypatch.setattr(fs, "build_opener", opener)
    return database


@pytest.mark.parametrize("message", [
    "Missing or insufficient permissions.",
    "Permission 'datastore.entities.get' denied on the requested resource.",
])
def test_evidence_isolation_checks_both_exact_fixtures(monkeypatch, message):
    seen = []

    def respond(request, *, timeout):
        seen.append(request.full_url)
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") == "Bearer synthetic-test"
        assert request.data is None and timeout == 30
        body = fs.canonical({"error": {"status": "PERMISSION_DENIED", "message": message}})
        raise HTTPError(request.full_url, 403, "", {}, BytesIO(body.encode()))

    isolation_transport(monkeypatch, respond).verify_isolation()
    assert seen == [
        f"https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/"
        "documents/_navmate_acceptance/migration_evidence_isolation_v1?mask.fieldPaths=synthetic_only"
        for project in ("navmate-prod", "navmate-6b281")
    ]


@pytest.mark.parametrize(("code", "payload"), [
    (302, {}),
    (401, {"error": {"status": "UNAUTHENTICATED"}}),
    (404, {"error": {"status": "NOT_FOUND"}}),
    (403, {"error": {"status": "PERMISSION_DENIED", "message": "API is disabled."}}),
    (403, {"error": {"status": "PERMISSION_DENIED", "message": "x" * 8192}}),
    (403, ["malformed"]),
])
def test_evidence_isolation_rejects_inconclusive_http_response(monkeypatch, code, payload):
    def respond(request, *, timeout):
        raise HTTPError(request.full_url, code, "", {}, BytesIO(fs.canonical(payload).encode()))

    with pytest.raises(app.Blocked, match=rf"inconclusive for navmate-prod \(HTTP {code}\)"):
        isolation_transport(monkeypatch, respond).verify_isolation()


def test_evidence_isolation_does_not_read_success_body(monkeypatch):
    @contextlib.contextmanager
    def respond(request, *, timeout):
        def unreadable():
            pytest.fail("Unexpected successful response body must not be read")

        yield SimpleNamespace(read=unreadable)

    with pytest.raises(app.Blocked, match="read was allowed"):
        isolation_transport(monkeypatch, respond).verify_isolation()


def test_evidence_isolation_sanitizes_transport_error(monkeypatch):
    def respond(request, *, timeout):
        raise URLError("sensitive remote detail")

    with pytest.raises(app.Blocked, match="^Evidence isolation unavailable for navmate-prod$"):
        isolation_transport(monkeypatch, respond).verify_isolation()


class Memory(fs.Firestore):
    def __init__(self):
        self.project = "demo-migration-evidence"
        self.root = f"projects/{self.project}/databases/(default)/documents"
        self.rows = {}
        self.lock = threading.RLock()

    @contextlib.contextmanager
    def transaction(self, *, write=False):
        with self.lock:
            yield copy.deepcopy(self.rows)

    def get(self, path, transaction=None):
        return copy.deepcopy((self.rows if transaction is None else transaction).get(path))

    def commit(self, writes, transaction=None):
        updated = copy.deepcopy(self.rows)
        for item in writes:
            if "delete" in item:
                updated.pop(item["delete"].removeprefix(self.root + "/"), None)
            else:
                name = item["update"]["name"].removeprefix(self.root + "/")
                if item.get("currentDocument", {}).get("exists") is False and name in updated:
                    raise app.Blocked("Already exists")
                updated[name] = {key: fs.decode(value)
                                 for key, value in item["update"]["fields"].items()}
        self.rows = updated

    def groups(self):
        return [name.split("/")[1] for name in list(self.rows)
                if name.startswith("migrationGroups/")]


@pytest.fixture(params=["memory", "emulator"])
def store(request):
    if request.param == "emulator":
        host = os.environ.get("MIGRATION_TEST_EMULATOR")
        if not host:
            pytest.skip("Dedicated Firestore emulator is run separately")
        database = fs.Firestore("demo-migration-evidence", emulator=host)
        # Corruption tests deliberately leave invalid sets. Isolate the next test's inventory.
        from urllib.request import Request, urlopen

        reset = "http://" + host + (
            "/emulator/v1/projects/demo-migration-evidence/databases/(default)/documents")
        with urlopen(Request(reset, method="DELETE"), timeout=10):
            pass
    else:
        database = Memory()
    return review.Reviews(database=database, env={
        "GITHUB_RUN_ID": str(uuid4().int % 10**18 + 1), "GITHUB_RUN_ATTEMPT": "1"})


def next_run(store):
    store.env["GITHUB_RUN_ID"] = str(int(store.env["GITHUB_RUN_ID"]) + 1)


def evidence():
    return review.signed_evidence({
        "schema_version": 1, "phase": "evidence", "result": "PASS",
        "publication_authorized": False, "candidate_sha": "a" * 40,
        "created_at": datetime.now(UTC).isoformat(),
        "identity": {"sha": "a" * 40, "current_sha": "b" * 40, "tooling_sha": "c" * 40},
        "checks": {"old_to_new": {"observations": {"sample_sha256": app.digest(SAMPLE.encode())}}},
        "configuration": CANARY,
    }, KEY)


SAMPLE = json.dumps(
    {"saved": {"sample": [[CANARY, 2]], "unicode": "原本"}, "latest": None}, indent=2)


def saved(store):
    value = evidence()
    return store.save(value, sample_json=SAMPLE), value


def prepared(store, prepared_at=None):
    ref, value = saved(store)
    next_run(store)
    store.begin(ref["id"], ref["sha256"], "prepare")
    plan = {"prepared_at": (prepared_at or datetime.now(UTC)).isoformat(), "settings": CANARY}
    raw = json.dumps(plan, indent=2) + "\n"
    data = {"schema_version": 1, "phase": "prepared", "created_at": datetime.now(UTC).isoformat(),
            "candidate_sha": "a" * 40, "publication_authorized": False,
            "plan": plan, "plan_sha256": app.digest(raw.encode()),
            "evidence_reference": {key: ref[key] for key in ("id", "sha256")}}
    result = store.save(data, root=ref["id"], plan_json=raw)
    return ref, result, data


def published(store, *, completed=None):
    parent, ref, plan = prepared(store)
    next_run(store)
    store.begin(ref["id"], ref["sha256"], "publish")
    data = {"schema_version": 1, "phase": "published", "created_at": (
        completed or datetime.now(UTC)).isoformat(), "final_verified": True,
        "evidence_reference": plan["evidence_reference"],
        "prepared_reference": {key: ref[key] for key in ("id", "sha256")}}
    result = store.save(data, root=parent["id"])
    return parent, ref, result


def replace(store, path, value):
    store.db.commit([store.db.put(path, value, create=False)])


def test_original_display_and_samples_roundtrip(store):
    ref, data = saved(store)
    assert store.read(ref["id"], ref["sha256"]) == data
    review.verify_evidence(data, KEY)
    sample = store.db.get("migrationRecords/" + ref["id"] + "-sample")
    assert sample["original_json"] == SAMPLE
    assert sample["display"]["saved"]["sample"]["[000000]"]["[000000]"] == CANARY


@pytest.mark.parametrize("fault", [
    "raw", "display", "sample", "missing-sample", "manifest", "root"])
def test_corruption_and_missing_documents_stop(store, fault):
    ref, _ = saved(store)
    path = "migrationRecords/" + ref["id"]
    value = store.db.get(path)
    if fault in ("sample", "missing-sample"):
        path += "-sample"
        value = store.db.get(path)
    if fault == "raw":
        value["original_json"] += " "
    elif fault in ("display", "sample"):
        value["display"]["changed"] = CANARY
    elif fault == "manifest":
        value["attachments"] = {}
    elif fault == "root":
        value["root_id"] = "r999-a1-evidence"
    if fault == "missing-sample":
        store.db.commit([{"delete": store.db.root + "/" + path}])
    else:
        replace(store, path, value)
    with pytest.raises(app.Blocked):
        store.read(ref["id"], ref["sha256"])


def test_exact_plan_original_is_required(store):
    parent, ref, data = prepared(store)
    assert store.read(ref["id"], ref["sha256"], comment=True) == data
    path = "migrationRecords/" + ref["id"] + "-plan"
    doc = store.db.get(path)
    doc["original_json"] = fs.canonical(data["plan"])
    doc = review.envelope(doc["original_json"], parent["id"])
    replace(store, path, doc)
    with pytest.raises(app.Blocked):
        store.read(ref["id"], ref["sha256"], comment=True)


def test_parent_substitution_does_not_authorize_prepared_plan(store):
    parent, ref, _ = prepared(store)
    next_run(store)
    replacement, _ = saved(store)
    path = "migrationGroups/" + parent["id"]
    group = store.db.get(path)
    group["evidence"] = {key: replacement[key] for key in ("id", "sha256")}
    replace(store, path, group)
    with pytest.raises(app.Blocked, match="parent"):
        store.read(ref["id"], ref["sha256"], comment=True)


@pytest.mark.parametrize("target", ["parent", "plan"])
def test_revoke_is_permanent_for_whole_set(store, target):
    parent, ref, _ = prepared(store)
    selected = parent if target == "parent" else ref
    next_run(store)
    first = store.revoke(selected["id"], selected["sha256"], "Yuto-24")
    next_run(store)
    assert store.revoke(selected["id"], selected["sha256"], "Yuto-24") == first
    for candidate, comment in ((parent, False), (ref, True)):
        with pytest.raises(app.Blocked, match="revoked"):
            store.read(candidate["id"], candidate["sha256"], comment=comment)
    assert store.cleanup(datetime.now(UTC) + timedelta(days=90)) == 0


@pytest.mark.parametrize("phase", ["evidence", "prepared"])
def test_expiry_fails_closed(store, phase):
    if phase == "evidence":
        data = evidence()
        data["created_at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        ref = store.save(data, sample_json=SAMPLE)
    else:
        _, ref, _ = prepared(store, prepared_at=datetime.now(UTC) - timedelta(minutes=31))
    with pytest.raises(app.Blocked):
        store.read(ref["id"], ref["sha256"], comment=phase == "prepared")


def test_duplicate_prepare_claim_never_reuses_evidence(store):
    ref, _ = saved(store)
    next_run(store)
    store.begin(ref["id"], ref["sha256"], "prepare")
    next_run(store)
    with pytest.raises(app.Blocked, match="already used"):
        store.begin(ref["id"], ref["sha256"], "prepare")
    assert store.cleanup(datetime.now(UTC) + timedelta(days=90)) == 0


@pytest.mark.parametrize("committed", [True, False])
def test_uncertain_write_is_read_back_and_never_replayed(store, monkeypatch, committed):
    original = store.db.commit
    calls = []

    def commit(writes, tx=None):
        calls.append(1)
        if committed:
            original(writes, tx)
        raise TimeoutError(CANARY)

    monkeypatch.setattr(store.db, "commit", commit)
    if committed:
        ref, value = saved(store)
        assert store.read(ref["id"], ref["sha256"]) == value
    else:
        with pytest.raises(app.Blocked, match="outcome unknown"):
            saved(store)
    assert len(calls) == 1


def test_document_capacity_stops_before_writing(store):
    value = evidence()
    value["oversize"] = "x" * fs.MAX_DOCUMENT
    with pytest.raises(app.Blocked, match="900 KiB"):
        store.save(value, sample_json=SAMPLE)
    assert store.db.get("migrationGroups/" + review.record_id(store.env, "evidence")) is None


def test_thirty_day_boundary_and_atomic_whole_set_removal(store):
    completed = datetime.now(UTC) - timedelta(days=30)
    parent, prepared_ref, final = published(store, completed=completed)
    assert store.cleanup(completed + timedelta(days=30) - timedelta(microseconds=1)) == 0
    assert store.cleanup(completed + timedelta(days=30)) == 1
    for ref in (parent, prepared_ref, final):
        assert store.db.get("migrationRecords/" + ref["id"]) is None
    assert store.db.get("migrationRecords/" + parent["id"] + "-sample") is None
    assert store.db.get("migrationRecords/" + prepared_ref["id"] + "-plan") is None


@pytest.mark.parametrize("state", [
    "EVIDENCE", "PREPARING", "PREPARED", "PUBLISHING", "BLOCKED", "UNKNOWN"])
def test_nonfinal_records_are_never_automatically_deleted(store, state):
    parent, _, _ = published(store, completed=datetime.now(UTC) - timedelta(days=40))
    path = "migrationGroups/" + parent["id"]
    group = store.db.get(path)
    group["state"] = state
    replace(store, path, group)
    assert store.cleanup() == 0
    assert store.db.get(path)


def test_concurrent_prepares_admit_only_one(store):
    ref, _ = saved(store)
    next_run(store)

    def claim(run):
        contender = review.Reviews(database=store.db, env={
            **store.env, "GITHUB_RUN_ID": str(int(store.env["GITHUB_RUN_ID"]) + run)})
        try:
            contender.begin(ref["id"], ref["sha256"], "prepare")
            return True
        except app.Blocked:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert sum(results) <= 1
    group = store.db.get("migrationGroups/" + ref["id"])
    assert group["state"] in ("EVIDENCE", "PREPARING")
    assert store.cleanup(datetime.now(UTC) + timedelta(days=90)) == 0


@pytest.mark.parametrize("legacy", ["514", "123456789012345", "", "https://github.com/example/issues/1"])
def test_legacy_identifiers_are_rejected(store, legacy):
    with pytest.raises(app.Blocked, match="regenerate legacy"):
        store.read(legacy, "a" * 64)


def test_summary_contains_no_private_plaintext(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    migration.report({"url": "https://console.firebase.google.com/project/demo/firestore",
                      "id": "r1-a1-evidence", "sha256": "a" * 64, "private": CANARY})
    captured = capsys.readouterr()
    assert CANARY not in summary.read_text() + captured.out + captured.err


def test_owner_only_approval():
    operator = SimpleNamespace(gh=lambda path: {"permission": "write", "user": {
        "login": path.split("/")[1], "type": "User"}})
    assert review.approved_actor(operator, {"GITHUB_ACTOR": "Yuto-24"}) == "Yuto-24"
    with pytest.raises(app.Blocked):
        review.approved_actor(operator, {"GITHUB_ACTOR": "someone"})


def test_schedule_cannot_start_publication_and_revoke_never_waits_for_lease():
    source = (app.ROOT / ".github/workflows/static-app-release.yml").read_text()
    workflow = yaml.safe_load(source)
    jobs = workflow["jobs"]
    for name in ("migration-revoke", "migration-cleanup"):
        assert "concurrency" not in jobs[name]
        text = json.dumps(jobs[name])
        assert "CLOUDFLARE" not in text and "STATIC_GOOGLE_SERVICE_ACCOUNT" not in text
        assert "STATIC_APP_RELEASE_GH_TOKEN" not in text
    for name, job in jobs.items():
        if name != "migration-cleanup":
            condition = job.get("if", "")
            assert "github.event_name" in condition
            assert "== 'schedule'" not in condition
    assert "STATIC_MIGRATION_REVIEW_TOKEN" not in source
    assert "STATIC_MIGRATION_REVIEW_REPOSITORY" not in source


def test_firestore_access_does_not_depend_on_github_visibility(store, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY_VISIBILITY", "private")
    ref, value = saved(store)
    monkeypatch.setenv("GITHUB_REPOSITORY_VISIBILITY", "public")
    assert store.read(ref["id"], ref["sha256"]) == value


def test_client_rules_deny_even_synthetic_documents(store):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    if isinstance(store.db, Memory):
        pytest.skip("Access control is tested against the emulator")
    ref, _ = saved(store)
    request = Request(store.db.base + "/migrationRecords/" + ref["id"])
    with pytest.raises(HTTPError) as error, urlopen(request, timeout=10):
        pass
    assert error.value.code == 403


def test_unknown_cleanup_result_never_replays_deletion(store, monkeypatch):
    parent, _, _ = published(store, completed=datetime.now(UTC) - timedelta(days=40))
    original = store.db.commit
    calls = []

    def commit(writes, tx=None):
        calls.append(1)
        original(writes, tx)
        raise TimeoutError(CANARY)

    monkeypatch.setattr(store.db, "commit", commit)
    assert store.cleanup() == 1
    assert len(calls) == 1
    assert store.db.get("migrationGroups/" + parent["id"]) is None


def test_revoke_between_read_and_mutation_stops(store):
    ref, _ = saved(store)
    store.read(ref["id"], ref["sha256"])
    next_run(store)
    store.revoke(ref["id"], ref["sha256"], "Yuto-24")
    next_run(store)
    with pytest.raises(app.Blocked, match="revoked"):
        store.begin(ref["id"], ref["sha256"], "prepare")


def test_failure_exception_and_journal_never_leak_to_logs(tmp_path, monkeypatch, capsys):
    import shutil

    class Reviews:
        def __init__(self, *_, **kwargs):
            pass

        def save(self, value, **kwargs):
            assert CANARY in value["result"]["reason"]
            return {"url": "https://console.firebase.google.com/project/demo/firestore",
                    "id": "r1-a1-blocked", "sha256": "b" * 64}

    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"operation": "evidence-migration"}}))
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(migration, "scope", lambda *_: "evidence-migration")
    monkeypatch.setattr(migration.migration_review, "Reviews", Reviews)
    monkeypatch.setattr(migration.transport, "key_bytes", lambda *_: (
        _ for _ in ()).throw(app.Blocked(CANARY)))
    monkeypatch.setattr(shutil, "rmtree", lambda *_: pytest.fail("No private files created"))
    assert migration.main() == 1
    captured = capsys.readouterr()
    assert CANARY not in summary.read_text() + captured.out + captured.err


def test_synthetic_acceptance_cannot_authorize_publication(store):
    parent, ref = migration.synthetic_acceptance(store)
    value = store.read(parent["id"], parent["sha256"])
    with pytest.raises(app.Blocked, match="sealed"):
        review.verify_evidence(value, KEY)
    assert store.read(ref["id"], ref["sha256"], comment=True)["synthetic_only"] is True
    assert store.cleanup(datetime.now(UTC) + timedelta(days=90)) == 0


def test_prepared_read_includes_parent_sample_and_revocation_in_one_transaction(store, monkeypatch):
    parent, ref, _ = prepared(store)
    calls = []
    original = store.db.get

    def get(path, tx=None):
        calls.append((path, tx))
        return original(path, tx)

    monkeypatch.setattr(store.db, "get", get)
    store.read(ref["id"], ref["sha256"], comment=True)
    assert len(calls) >= 6
    assert calls[0][1] is not None
    assert all(token is calls[0][1] for _, token in calls)
    paths = [path for path, _ in calls]
    assert "migrationRecords/" + parent["id"] + "-sample" in paths
    assert "migrationRevocations/" + parent["id"] in paths


def test_plaintext_canary_never_enters_transfer_artifact(tmp_path, monkeypatch):
    from scripts.static_ops import schema260_bundle as bundle

    monkeypatch.setattr(bundle, "archive_files", lambda *args, **kwargs: [
        ("store/plan.json", json.dumps({"configuration": CANARY}).encode()),
        ("evidence/sample.json", CANARY.encode()),
    ])
    result = tmp_path / "result.aesgcm"
    bundle.seal(tmp_path, {}, KEY, result, success=True)
    assert CANARY.encode() not in result.read_bytes()
    source = (app.ROOT / ".github/workflows/static-app-release.yml").read_text()
    job = yaml.safe_load(source)["jobs"]["migration-prepare"]
    uploads = [step for step in job["steps"] if "upload-artifact@" in step.get("uses", "")]
    assert len(uploads) == 1
    assert uploads[0]["with"]["path"].endswith(".aesgcm")


def test_evidence_credentials_are_not_in_candidate_operator_environment(tmp_path, monkeypatch):
    captured = []

    class Reviews:
        def __init__(self, *_args, **_kwargs):
            assert os.environ["STATIC_MIGRATION_EVIDENCE_CREDENTIALS_FILE"] == CANARY

        def save(self, *_args, **_kwargs):
            return {"url": "https://console.firebase.google.com/project/demo/firestore",
                    "id": "r1-a1-blocked", "sha256": "b" * 64}

    class Candidate:
        def __init__(self):
            captured.append(dict(os.environ))
            raise app.Blocked("Synthetic stop before candidate work")

    event = tmp_path / "event.json"
    event.write_text('{}')
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    monkeypatch.setenv("STATIC_MIGRATION_EVIDENCE_CREDENTIALS_FILE", CANARY)
    monkeypatch.setattr(migration, "scope", lambda *_: "evidence-migration")
    monkeypatch.setattr(migration.migration_review, "Reviews", Reviews)
    monkeypatch.setattr(migration.transport, "key_bytes", lambda *_: KEY)
    monkeypatch.setattr(migration, "MigrationOperator", Candidate)
    assert migration.main() == 1
    assert len(captured) == 1
    assert "STATIC_MIGRATION_EVIDENCE_CREDENTIALS_FILE" not in captured[0]


@pytest.mark.parametrize("application,evidence_project,allowed", [
    ("", "demo-evidence-project", False),
    ("bad/id", "demo-evidence-project", False),
    ("demo-production-app", "demo-production-app", False),
    ("demo-production-app", "navmate-6b281", False),
    ("demo-production-app", "demo-evidence-project", True),
])
def test_evidence_project_must_be_distinct_from_known_application(
    monkeypatch, application, evidence_project, allowed,
):
    marker = object()
    monkeypatch.setattr(fs, "Firestore", lambda *_args: marker)
    env = {"VITE_FIREBASE_PROJECT_ID": application,
           "STATIC_MIGRATION_EVIDENCE_PROJECT_ID": evidence_project,
           "STATIC_MIGRATION_EVIDENCE_ENABLED": "true"}
    if allowed:
        assert fs.configured(env) is marker
    else:
        with pytest.raises(app.Blocked):
            fs.configured(env)


def test_every_migration_job_receives_application_project_for_isolation():
    source = (app.ROOT / ".github/workflows/static-app-release.yml").read_text()
    jobs = yaml.safe_load(source)["jobs"]
    for name, job in jobs.items():
        if name.startswith("migration-"):
            step = next(step for step in job["steps"]
                        if step.get("run") == "python scripts/static_ops/migration_release.py")
            assert step["env"]["VITE_FIREBASE_PROJECT_ID"] == "${{ vars.VITE_FIREBASE_PROJECT_ID }}"


@pytest.mark.parametrize("attachment", [False, True])
@pytest.mark.parametrize("replacement", [0, 0.0])
def test_display_type_substitution_is_rejected(store, attachment, replacement):
    raw = json.dumps({"nested": [[False]]})
    value = evidence()
    value["checks"]["old_to_new"]["observations"]["sample_sha256"] = app.digest(raw.encode())
    ref = store.save(value, sample_json=raw)
    assert store.read(ref["id"], ref["sha256"])["publication_authorized"] is False
    path = "migrationRecords/" + ref["id"] + ("-sample" if attachment else "")
    doc = store.db.get(path)
    if attachment:
        doc["display"]["nested"]["[000000]"]["[000000]"] = replacement
    else:
        doc["display"]["publication_authorized"] = replacement
    replace(store, path, doc)
    with pytest.raises(app.Blocked, match="display differ|attachment changed"):
        store.read(ref["id"], ref["sha256"])


def test_firestore_tags_preserve_numeric_types():
    assert type(fs.decode({"doubleValue": 0})) is float
    assert type(fs.decode({"integerValue": "0"})) is int
    assert type(fs.decode({"booleanValue": False})) is bool
    assert fs.same({"nested": [False, 0, 0.0]}, {"nested": [False, 0, 0.0]})
    assert not fs.same({"nested": [0]}, {"nested": [0.0]})


def test_published_group_rejects_blocked_save(store):
    parent, _, _ = published(store, completed=datetime.now(UTC) - timedelta(days=40))
    before = store.db.get("migrationGroups/" + parent["id"])
    next_run(store)
    with pytest.raises(app.Blocked, match="Published evidence cannot become blocked"):
        store.save({"schema_version": 1, "phase": "blocked", "created_at":
                    datetime.now(UTC).isoformat()}, root=parent["id"])
    assert store.db.get("migrationGroups/" + parent["id"]) == before
    assert store.db.get("migrationRecords/" + review.record_id(store.env, "blocked")) is None
    assert store.cleanup() == 1


@pytest.mark.parametrize("target", ["evidence", "prepared", "published", "blocked"])
def test_revoke_rejects_record_redirected_to_another_group(store, target):
    parent, plan, final = published(store)
    if target == "blocked":
        next_run(store)
        ref = store.save({"schema_version": 1, "phase": "blocked"})
    else:
        ref = {"evidence": parent, "prepared": plan, "published": final}[target]
    next_run(store)
    other, _ = saved(store)
    path = "migrationRecords/" + ref["id"]
    doc = store.db.get(path)
    doc["root_id"] = other["id"]
    replace(store, path, doc)
    # Keep attachments internally consistent to exercise group membership validation.
    for label in doc["attachments"]:
        part_path = path + "-" + label
        part = store.db.get(part_path)
        part["root_id"] = other["id"]
        replace(store, part_path, part)
    next_run(store)
    with pytest.raises(app.Blocked):
        store.revoke(ref["id"], ref["sha256"], "Yuto-24")
    for root in (parent["id"], other["id"]):
        assert store.db.get("migrationRevocations/" + root) is None
        assert store.db.get("migrationGroups/" + root)["revoked"] is False


def test_revoke_published_record_checks_original_parent(store):
    parent, _, final = published(store)
    next_run(store)
    other, _ = saved(store)
    path = "migrationRecords/" + final["id"]
    doc = store.db.get(path)
    doc["root_id"] = other["id"]
    replace(store, path, doc)
    group_path = "migrationGroups/" + other["id"]
    group = store.db.get(group_path)
    group["published"] = {key: final[key] for key in ("id", "sha256")}
    replace(store, group_path, group)
    next_run(store)
    with pytest.raises(app.Blocked, match="Published evidence parent changed"):
        store.revoke(final["id"], final["sha256"], "Yuto-24")
    assert store.db.get("migrationRevocations/" + other["id"]) is None
    # An unmodified publication remains revocable.
    doc["root_id"] = parent["id"]
    replace(store, path, doc)
    store.revoke(final["id"], final["sha256"], "Yuto-24")
    assert store.db.get("migrationGroups/" + parent["id"])["revoked"] is True


def test_cleanup_retains_invalid_set_but_deletes_later_valid_set(store, monkeypatch):
    expired = datetime.now(UTC) - timedelta(days=40)
    bad, bad_plan, bad_final = published(store, completed=expired)
    next_run(store)
    good, _, _ = published(store, completed=expired)
    missing = "migrationRecords/" + bad["id"] + "-sample"
    store.db.commit([{"delete": store.db.root + "/" + missing}])
    monkeypatch.setattr(store.db, "groups", lambda: [bad["id"], good["id"]])
    with pytest.raises(app.Blocked, match=bad["id"]):
        store.cleanup()
    assert store.db.get("migrationGroups/" + good["id"]) is None
    for ref in (bad, bad_plan, bad_final):
        assert store.db.get("migrationRecords/" + ref["id"]) is not None


def test_cleanup_does_not_swallow_unexpected_validation_errors(store, monkeypatch):
    parent, _, _ = published(store, completed=datetime.now(UTC) - timedelta(days=40))
    monkeypatch.setattr(store, "document", lambda *_: (_ for _ in ()).throw(RuntimeError(CANARY)))
    with pytest.raises(RuntimeError, match=CANARY):
        store.cleanup()
    assert store.db.get("migrationGroups/" + parent["id"])


@pytest.mark.parametrize("fail_save", [False, True])
def test_notification_failure_after_publication_does_not_block_evidence(
    tmp_path, monkeypatch, capsys, fail_save,
):
    store = review.Reviews(database=Memory(), env={
        "GITHUB_RUN_ID": str(uuid4().int % 10**18 + 1), "GITHUB_RUN_ATTEMPT": "1"})
    parent, ref, _ = prepared(store)
    next_run(store)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {
        "migration_record_id": ref["id"], "reviewed_record_sha256": ref["sha256"]}}))
    for key, value in {**store.env, "GITHUB_EVENT_PATH": str(event),
                       "GITHUB_SHA": "a" * 40, "RUNNER_TEMP": str(tmp_path)}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(migration, "scope", lambda *_: "publish-migration")
    monkeypatch.setattr(review, "Reviews", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(review, "approved_actor", lambda *_: "Yuto-24")
    monkeypatch.setattr(migration.transport, "key_bytes", lambda *_: KEY)
    operator = SimpleNamespace(git=lambda *args: "a" * 40 if args[0] == "rev-parse" else "")
    monkeypatch.setattr(migration, "MigrationOperator", lambda: operator)
    monkeypatch.setattr(migration.migration_archive, "download", lambda *_: tmp_path / "archive")
    monkeypatch.setattr(migration.migration_archive, "restore", lambda *_: None)
    monkeypatch.setattr(migration.migration_archive, "evidence_run", lambda *_: None)
    finishes = []
    journal = SimpleNamespace(value={"sha": "a" * 40},
                              finish=lambda success, **_: finishes.append(success))
    monkeypatch.setattr(app, "Journal", lambda *_: journal)
    monkeypatch.setattr(migration, "publish", lambda *_: None)
    monkeypatch.setattr(migration.diagnostics, "record_failure", lambda *_: None)
    monkeypatch.setattr(migration, "report", lambda *_: (_ for _ in ()).throw(OSError(CANARY)))
    save = store.save

    def save_record(value, **kwargs):
        if fail_save and value["phase"] == "published":
            raise app.Blocked(CANARY)
        return save(value, **kwargs)

    monkeypatch.setattr(store, "save", save_record)
    assert migration.main() == 1
    group = store.db.get("migrationGroups/" + parent["id"])
    assert group["state"] == ("BLOCKED" if fail_save else "PUBLISHED")
    assert finishes == ([True, False] if fail_save else [True])
    captured = capsys.readouterr()
    assert CANARY not in captured.out + captured.err
    if not fail_save:
        assert "Migration BLOCKED" not in captured.out + captured.err
        assert group["blocked"] == {}
        assert store.cleanup(datetime.now(UTC) + timedelta(days=31)) == 1
