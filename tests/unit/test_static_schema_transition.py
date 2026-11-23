"""Manual one-way schema evidence; automatic/default updates remain fail closed."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_static_app_release import NEW, OLD, SimulatedOperator

from scripts.static_ops import app_release as app
from scripts.static_ops import publication_gate as gate
from scripts.static_ops.release_automation import ActionsOperator

TOOL = "d" * 40
SCHEMA = "data/schemas/project.schema.json"
WRITER = "web/src/localProjectRepository.ts"
ROLES = ("old_to_new", "old_writer_fenced", "storage_sync_roundtrip")


def blob(source):
    return hashlib.sha1(source.encode(), usedforsecurity=False).hexdigest()


def writer_source(version):
    declaration = "" if version == 1 else f"export const LOCAL_DATABASE_VERSION = {version};"
    argument = "1" if version == 1 else "LOCAL_DATABASE_VERSION"
    return declaration + """
export class IndexedDbProjectRepository {
  constructor(private readonly factory: () => IDBFactory = () => indexedDB,) {}
  private database(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const scope = this.context?.storage_id ?? this.context?.account_id;
      const request = this.factory().open(NAME_ARG, VERSION_ARG);
    });
  }
}
""".replace("VERSION_ARG", argument).replace(
        "NAME_ARG", "scope ? `${LOCAL_DATABASE}.${scope}` : LOCAL_DATABASE"
    )


@pytest.fixture(params=["reference-snapshot-writer-fence", "forecast-model-selection",
                        "aip-reference-source-writer-fence"])
def reviewed(tmp_path, request):
    before = {"$defs": {"RouteNode": {"properties": {"name": {"type": "string"}}}}}
    after = copy.deepcopy(before)
    after["$defs"].update(ReferencePointSnapshot={}, ReferencePointSource={})
    after["$defs"]["RouteNode"]["properties"]["reference_snapshot"] = {
        "anyOf": [{"$ref": "#/$defs/ReferencePointSnapshot"}, {"type": "null"}],
        "default": None,
    }
    forecast = request.param == "forecast-model-selection"
    aip = request.param == "aip-reference-source-writer-fence"
    if forecast:
        root = Path(__file__).resolve().parents[2]
        before = json.loads((root / "tests/fixtures/schema4/project.schema.json").read_text())
        # This evidence covers the historical forecast-only transition. Later
        # schema additions must not silently become part of its reviewed fixture.
        after = copy.deepcopy(before)
        current = json.loads((root / SCHEMA).read_text())
        after["properties"]["selected_forecast_model"] = current["properties"][
            "selected_forecast_model"
        ]
        after["properties"]["schema_version"].update(const=5, default=5)
    if aip:
        root = Path(__file__).resolve().parents[2]
        after = json.loads((root / SCHEMA).read_text())
        before = copy.deepcopy(after)
        before["$defs"].pop("AipReferencePointSource")
        before["$defs"]["ReferencePointSnapshot"]["description"] = (
            "Selection-time reference data, never refreshed implicitly from a master.")
        before["$defs"]["ReferencePointSnapshot"]["properties"]["source"] = {
            "$ref": "#/$defs/ReferencePointSource",
        }
    sources = {
        (OLD, SCHEMA): json.dumps(before),
        (NEW, SCHEMA): json.dumps(after),
        (OLD, WRITER): writer_source(1),
        (
            NEW,
            WRITER,
        ): writer_source(2),
        (OLD, app.COMPATIBILITY[0]): "rules",
        (NEW, app.COMPATIBILITY[0]): "rules",
        (OLD, app.COMPATIBILITY[1]): "indexes",
        (NEW, app.COMPATIBILITY[1]): "indexes",
    }
    if forecast or aip:
        sources[OLD, WRITER] = sources[NEW, WRITER]
    if aip:
        sources[NEW, WRITER] = sources[NEW, WRITER].replace("VERSION = 2;", "VERSION = 3;")
    path = tmp_path / "schema-transition.json"
    operator = app.Operator(tmp_path, schema_transition=path)

    def git(*args):
        if args == ("rev-parse", "HEAD"):
            return TOOL
        sha, name = args[-1].split(":", 1)
        return blob(sources[sha, name]) if args[0] == "rev-parse" else sources[sha, name]

    operator.git = git
    operator.rules_source = lambda sha: sources[sha, app.COMPATIBILITY[0]]
    variables = {name: "synthetic" for name in gate.CONFIGURATION}
    variables["VITE_FIREBASE_PROJECT_ID"] = "test-project"
    record = {
        "schema_version": 1,
        "kind": request.param,
        "sha": NEW,
        "current_sha": OLD,
        "tooling_sha": TOOL,
        "project": "test-project",
        "origin": gate.ORIGIN,
        "configuration_digest": app.fingerprint(app.public_configuration(variables)),
        "direction": "old-to-new",
        "recovery": "forward-fix; preserve Project data",
        "database_version": 3 if aip else 2,
        "before_blob": blob(sources[OLD, SCHEMA]),
        "after_blob": blob(sources[NEW, SCHEMA]),
        "writer_blob": blob(sources[NEW, WRITER]),
        "checks": {},
    }
    if forecast:
        record["latest_policy"] = "replace-own-device-latest-on-open"
    roles = (("old_to_new", "old_writer_coexistence", "storage_sync_roundtrip")
             if forecast else ROLES)
    for role in roles:
        evidence = tmp_path / (role + ".txt")
        evidence.write_text("Synthetic reviewed result: " + role)
        record["checks"][role] = {
            "result": "PASS",
            "reviewed_by": "synthetic-reviewer",
            "summary": role,
            "record": {"path": evidence.name, "sha256": app.digest(evidence.read_bytes())},
        }
        if forecast or aip:
            app.write_json(evidence, {
                "identity": {key: value for key, value in record.items() if key != "checks"},
                "check": role,
                **{key: record["checks"][role][key]
                   for key in ("result", "reviewed_by", "summary")},
            })
            record["checks"][role]["record"]["sha256"] = app.digest(evidence.read_bytes())
    app.write_json(path, record)
    calls = []

    def rules_get(resource):
        calls.append(resource)
        if "/releases/" in resource:
            return {"rulesetName": "projects/test-project/rulesets/current"}
        return {"source": {"files": [{"content": "rules"}]}}

    operator.rules_get = rules_get
    return operator, path, record, sources, variables, calls


def test_exact_reviewed_transition_reads_rules_but_does_not_write_them(reviewed):
    operator, path, record, _, variables, calls = reviewed
    digest = operator.compatibility(NEW, OLD, variables)
    assert len(digest) == 64 and len(calls) == 3
    assert operator.schema_receipt["record"] == record
    assert operator.schema_receipt["sha256"] == app.digest(path.read_bytes())
    assert set(operator.schema_receipt["evidence"]) == set(record["checks"])
    assert operator.rules_receipt["transition"] is None


def test_unchanged_reviewed_transition_survives_prepare_publish(reviewed):
    real, _, record, _, variables, _ = reviewed
    operator = SimulatedOperator(real.root, automation="false")
    operator.state["variables"].update(variables)

    def refresh(simulated, paused):
        simulated.state["rules_digest"] = real.compatibility(NEW, OLD, variables)
        simulated.state["schema_receipt"] = copy.deepcopy(real.schema_receipt)

    operator.snapshot_hook = refresh
    store = real.root / "store"
    store.mkdir(mode=0o700)
    app.prepare(
        operator, NEW, OLD, store, app.Journal(store / "prepare-status.json", "prepare", NEW)
    )
    app.publish(operator, NEW, OLD, store, app.digest((store / "plan.json").read_bytes()),
                app.Journal(store / "publish-status.json", "publish", NEW))
    assert operator.uploaded is not None
    plan = json.loads((store / "plan.json").read_text())
    assert plan["snapshot"]["schema_receipt"]["record"] == record


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", True),
        ("kind", "generic"),
        ("kind", []),
        ("sha", OLD),
        ("current_sha", NEW),
        ("tooling_sha", OLD),
        ("project", "other"),
        ("origin", "https://other.example"),
        ("configuration_digest", "unknown"),
        ("direction", "bidirectional"),
        ("recovery", "rollback"),
        ("database_version", True),
        ("database_version", 1),
        ("before_blob", "wrong"),
        ("after_blob", "wrong"),
        ("writer_blob", "wrong"),
        ("checks", {}),
    ],
)
def test_mismatched_or_unverified_record_blocks_before_provider_reads(reviewed, key, value):
    operator, path, record, _, variables, calls = reviewed
    record[key] = value
    app.write_json(path, record)
    with pytest.raises(app.Blocked):
        operator.compatibility(NEW, OLD, variables)
    assert calls == [] and operator.rules_receipt is None


@pytest.mark.parametrize(
    "damage", ["missing", "invalid", "withdrawn", "reviewer", "evidence", "hash", "path"]
)
def test_missing_withdrawn_or_replaced_evidence_is_not_acceptance(reviewed, damage):
    operator, path, record, _, variables, calls = reviewed
    if damage == "missing":
        path.unlink()
    elif damage == "invalid":
        path.write_text("[]")
    else:
        check = record["checks"]["old_to_new"]
        if damage == "withdrawn":
            check["result"] = "UNKNOWN"
        elif damage == "reviewer":
            check["reviewed_by"] = " "
        elif damage == "evidence":
            (path.parent / check["record"]["path"]).write_text("replaced")
        elif damage == "hash":
            check["record"]["sha256"] = "f" * 64
        else:
            check["record"]["path"] = "missing-file"
        app.write_json(path, record)
    with pytest.raises(app.Blocked):
        operator.compatibility(NEW, OLD, variables)
    assert calls == []


@pytest.mark.parametrize(
    "change", ["required", "type", "indexes", "writer", "writer-use", "previous-writer"]
)
def test_record_cannot_authorize_broader_schema_or_unfenced_candidate(reviewed, change):
    operator, path, record, sources, variables, _ = reviewed
    if change in {"required", "type"}:
        schema = json.loads(sources[NEW, SCHEMA])
        if change == "required":
            schema["required"] = ["new_required_field"]
        else:
            schema["$defs"]["RouteNode"]["properties"]["name"]["type"] = "integer"
        sources[NEW, SCHEMA] = json.dumps(schema)
        record["after_blob"] = blob(sources[NEW, SCHEMA])
    elif change == "indexes":
        sources[NEW, app.COMPATIBILITY[1]] = "changed index"
    else:
        sources[NEW if change != "previous-writer" else OLD, WRITER] = (
            "factory.open(name, 1)"
            if change == "writer"
            else "export const LOCAL_DATABASE_VERSION = 2;"
        )
        record["writer_blob"] = blob(sources[NEW, WRITER])
    app.write_json(path, record)
    with pytest.raises(app.Blocked):
        operator.compatibility(NEW, OLD, variables)


def test_normal_and_actions_operator_still_reject_changed_schema(reviewed):
    operator, _, _, _, variables, calls = reviewed
    for target in (app.Operator(operator.root), ActionsOperator({"id": 1})):
        target.git, target.rules_source, target.rules_get = (
            operator.git,
            operator.rules_source,
            operator.rules_get,
        )
        assert target.schema_transition is None
        with pytest.raises(app.Blocked, match="migration required"):
            target.compatibility(NEW, OLD, variables)
    assert calls == []


@pytest.mark.parametrize("change", ["record", "evidence", "source", "path"])
def test_prepare_publish_binds_exact_record_evidence_and_candidate(reviewed, change):
    real, path, record, sources, variables, _ = reviewed
    operator = SimulatedOperator(real.root, automation="false")
    operator.state["variables"].update(variables)

    def refresh(simulated, paused):
        simulated.state["rules_digest"] = real.compatibility(NEW, OLD, variables)
        simulated.state["schema_receipt"] = copy.deepcopy(real.schema_receipt)

    operator.snapshot_hook = refresh
    store = real.root / "store"
    store.mkdir(mode=0o700)
    app.prepare(
        operator, NEW, OLD, store, app.Journal(store / "prepare-status.json", "prepare", NEW)
    )
    plan = json.loads((store / "plan.json").read_text())
    assert plan["snapshot"]["schema_receipt"]["record"] == record
    if change == "record":
        record["checks"]["old_to_new"]["summary"] = "different reviewed result"
        app.write_json(path, record)
    elif change == "evidence":
        reference = record["checks"]["old_to_new"]["record"]
        (path.parent / reference["path"]).write_text("different result")
    elif change == "source":
        sources[NEW, WRITER] += " changed"
    else:
        other = path.with_name("replacement.json")
        other.write_bytes(path.read_bytes())
        real.schema_transition = other
    with pytest.raises(app.Blocked):
        app.publish(
            operator,
            NEW,
            OLD,
            store,
            app.digest((store / "plan.json").read_bytes()),
            app.Journal(store / "publish-status.json", "publish", NEW),
        )
    assert operator.uploaded is None


def test_rules_transition_is_reused_alongside_schema_evidence(reviewed):
    from test_static_app_release import transition_record

    operator, path, record, sources, variables, _ = reviewed
    sources[OLD, app.COMPATIBILITY[0]] = "old rules"
    operator.rules_transition = path.with_name("rules-transition.json")
    transition_record(
        operator.rules_transition, project="test-project", before="old rules", after="rules"
    )
    original = operator.rules_get

    def named(resource):
        value = original(resource)
        if "/rulesets/" in resource:
            value["source"]["files"][0]["name"] = "firebase/firestore.rules"
        return value

    operator.rules_get = named
    if record["kind"] != "reference-snapshot-writer-fence":
        with pytest.raises(app.Blocked, match="identical Rules/indexes"):
            operator.compatibility(NEW, OLD, variables)
        return
    assert len(operator.compatibility(NEW, OLD, variables)) == 64
    assert operator.rules_receipt["transition"]["record"]["sha"] == NEW
    assert operator.schema_receipt["record"]["sha"] == NEW


@pytest.mark.parametrize("reviewed", ["forecast-model-selection"], indirect=True)
@pytest.mark.parametrize("change", ["model", "required", "version", "boolean-default",
                                  "reference-source",
                                  "latest-policy", "rules", "report-identity", "report-boolean",
                                  "report-role", "report-review", "report-json"])
def test_forecast_transition_rejects_unreviewed_contracts(reviewed, change):
    operator, path, record, sources, variables, calls = reviewed
    if change in {"model", "required", "version", "boolean-default", "reference-source"}:
        after = json.loads(sources[NEW, SCHEMA])
        if change == "model":
            after["properties"]["selected_forecast_model"]["anyOf"][0]["enum"].append("OTHER")
        elif change == "required":
            after["required"].append("selected_forecast_model")
        elif change == "version":
            after["properties"]["schema_version"]["const"] = 6
        elif change == "reference-source":
            root = Path(__file__).resolve().parents[2]
            current = json.loads((root / SCHEMA).read_text())
            for definition in ("AipReferencePointSource", "ReferencePointSnapshot"):
                after["$defs"][definition] = current["$defs"][definition]
        else:
            # Python True == 1 must not admit a different JSON schema default.
            after["properties"]["run_up_included"]["default"] = 1
        sources[NEW, SCHEMA] = json.dumps(after)
        record["after_blob"] = blob(sources[NEW, SCHEMA])
        for check in record["checks"].values():
            evidence = path.parent / check["record"]["path"]
            report = json.loads(evidence.read_text())
            report["identity"]["after_blob"] = record["after_blob"]
            app.write_json(evidence, report)
            check["record"]["sha256"] = app.digest(evidence.read_bytes())
    elif change == "latest-policy":
        record["latest_policy"] = "preserve-every-latest"
    elif change == "rules":
        sources[NEW, app.COMPATIBILITY[0]] = "new rules"
    else:
        reference = record["checks"]["old_to_new"]["record"]
        evidence = path.parent / reference["path"]
        report = json.loads(evidence.read_text())
        if change == "report-identity":
            report["identity"]["sha"] = OLD
        elif change == "report-boolean":
            report["identity"]["schema_version"] = True
        elif change == "report-role":
            report["check"] = "storage_sync_roundtrip"
        elif change == "report-review":
            report["reviewed_by"] = "someone else"
        evidence.write_text("not json" if change == "report-json" else json.dumps(report))
        reference["sha256"] = app.digest(evidence.read_bytes())
    app.write_json(path, record)
    with pytest.raises(app.Blocked):
        operator.compatibility(NEW, OLD, variables)
    assert not calls


@pytest.mark.parametrize("reviewed", ["forecast-model-selection",
                                     "aip-reference-source-writer-fence"], indirect=True)
@pytest.mark.parametrize("field", ["sha", "current_sha", "tooling_sha", "project",
                                   "configuration_digest"])
def test_report_cannot_be_retargeted_with_edited_outer_record(reviewed, field):
    operator, path, record, sources, variables, calls = reviewed
    candidate, current = NEW, OLD
    other = "e" * 40
    if field in {"sha", "current_sha"}:
        previous = NEW if field == "sha" else OLD
        for (sha, name), content in list(sources.items()):
            if sha == previous:
                sources[other, name] = content
        candidate, current = (other, OLD) if field == "sha" else (NEW, other)
        record[field] = other
    elif field == "tooling_sha":
        git = operator.git
        operator.git = lambda *args: other if args == ("rev-parse", "HEAD") else git(*args)
        record[field] = other
    elif field == "project":
        variables["VITE_FIREBASE_PROJECT_ID"] = record[field] = "different-project"
        record["configuration_digest"] = app.fingerprint(app.public_configuration(variables))
    else:
        variables["VITE_FIREBASE_API_KEY"] = "different-public-config"
        record[field] = app.fingerprint(app.public_configuration(variables))
    app.write_json(path, record)
    with pytest.raises(app.Blocked, match="report identity"):
        operator.compatibility(candidate, current, variables)
    assert not calls


@pytest.mark.parametrize("reviewed", ["aip-reference-source-writer-fence"], indirect=True)
@pytest.mark.parametrize("change", ["source-constraint", "source-required", "union", "legacy",
                                  "boolean-default", "schema-version", "description",
                                  "rules", "database",
                                  "report-identity", "report-role", "report-json"])
def test_aip_transition_rejects_unreviewed_contracts(reviewed, change):
    operator, path, record, sources, variables, calls = reviewed
    if change in {"source-constraint", "source-required", "union", "legacy",
                  "boolean-default", "schema-version", "description"}:
        after = json.loads(sources[NEW, SCHEMA])
        definitions = after["$defs"]
        if change == "source-constraint":
            definitions["AipReferencePointSource"]["properties"]["record_index"]["minimum"] = -1
        elif change == "source-required":
            definitions["AipReferencePointSource"]["required"].remove("sha256")
        elif change == "union":
            definitions["ReferencePointSnapshot"]["properties"]["source"]["anyOf"].append(
                {"type": "null"})
        elif change == "legacy":
            definitions["ReferencePointSource"]["additionalProperties"] = True
        elif change == "boolean-default":
            after["properties"]["run_up_included"]["default"] = 1
        elif change == "description":
            definitions["ReferencePointSnapshot"]["description"] = "unreviewed description"
        else:
            after["properties"]["schema_version"]["const"] = 6
        sources[NEW, SCHEMA] = json.dumps(after)
        record["after_blob"] = blob(sources[NEW, SCHEMA])
        for check in record["checks"].values():
            evidence = path.parent / check["record"]["path"]
            report = json.loads(evidence.read_text())
            report["identity"]["after_blob"] = record["after_blob"]
            app.write_json(evidence, report)
            check["record"]["sha256"] = app.digest(evidence.read_bytes())
    elif change == "rules":
        sources[NEW, app.COMPATIBILITY[0]] = "changed rules"
    elif change == "database":
        record["database_version"] = 2
    else:
        reference = record["checks"]["old_writer_fenced"]["record"]
        evidence = path.parent / reference["path"]
        report = json.loads(evidence.read_text())
        if change == "report-identity":
            report["identity"]["database_version"] = 2
        elif change == "report-role":
            report["check"] = "old_writer_coexistence"
        evidence.write_text("not json" if change == "report-json" else json.dumps(report))
        reference["sha256"] = app.digest(evidence.read_bytes())
    app.write_json(path, record)
    with pytest.raises(app.Blocked):
        operator.compatibility(NEW, OLD, variables)
    assert not calls
