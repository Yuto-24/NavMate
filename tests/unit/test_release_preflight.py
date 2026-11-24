"""Existing migration recognition never grants compatibility or publication approval."""

import copy
import json

import pytest

from scripts.static_ops import app_release as app
from scripts.static_ops import release_preflight as preflight
from tests.unit import test_static_schema_transition as schema_cases
from tests.unit.test_static_schema_transition import NEW, OLD, SCHEMA, WRITER

reviewed = schema_cases.reviewed


def test_supported_shape_still_needs_reviewed_evidence(reviewed):
    operator, path, record, sources, _, _ = reviewed
    path.unlink()
    route = preflight.classify(operator, NEW, OLD)
    if record["kind"] != preflight.KINDS[2]:
        assert route["route"] == "BLOCKED"
        return
    assert route["route"] == "MANUAL"
    assert route["kind"] == record["kind"]
    assert route["publication_authorized"] is False
    assert set(route["required_checks"]) == set(record["checks"])
    with pytest.raises(app.Blocked, match="unavailable"):
        operator.reviewed_schema(NEW, OLD, {})


def test_ordinary_route_has_no_manual_evidence_requirement(reviewed):
    operator, path, _, sources, _, _ = reviewed
    sources[OLD, SCHEMA] = sources[NEW, SCHEMA]
    sources[OLD, WRITER] = sources[NEW, WRITER]
    path.unlink()
    result = preflight.classify(operator, NEW, OLD)
    assert result["route"] == "AUTOMATIC"
    assert result["changed_contracts"] == []
    assert result["publication_authorized"] is False


@pytest.mark.parametrize("path", app.COMPATIBILITY[:2])
def test_rules_and_indexes_changes_never_get_known_migration_route(reviewed, path):
    operator, _, _, sources, _, _ = reviewed
    sources[NEW, path] += " changed"
    assert preflight.classify(operator, NEW, OLD)["route"] == "BLOCKED"


def test_additional_schema_change_fails_closed(reviewed):
    operator, _, _, sources, _, _ = reviewed
    value = json.loads(sources[NEW, SCHEMA])
    value["additionalProperties"] = True
    sources[NEW, SCHEMA] = json.dumps(value)
    assert preflight.classify(operator, NEW, OLD)["route"] == "BLOCKED"


def test_database_upgrade_without_supported_schema_change_fails(reviewed):
    operator, _, _, sources, _, _ = reviewed
    sources[OLD, SCHEMA] = sources[NEW, SCHEMA]
    sources[NEW, WRITER] = (
        schema_cases.writer_source(99)
    )
    assert preflight.classify(operator, NEW, OLD)["route"] == "BLOCKED"


def test_provider_failure_is_not_automatic(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(preflight.sys, "argv", ["preflight", "--sha", NEW])
    monkeypatch.setattr(
        preflight,
        "inspect",
        lambda *_: (_ for _ in ()).throw(RuntimeError("private configuration detail")),
    )
    summary, output = tmp_path / "summary", tmp_path / "output"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert preflight.main() == 1
    assert "private configuration detail" not in summary.read_text() + capsys.readouterr().out
    assert output.read_text() == "route=BLOCKED\n"


def test_preflight_rechecks_configuration_and_canonical(reviewed, monkeypatch):
    operator, _, _, sources, variables, _ = reviewed
    variables["STATIC_APPROVED_SHA"] = OLD
    canonical = {
        "commit": OLD,
        "dirty": False,
        "configuration": app.public_configuration(variables),
    }
    monkeypatch.setattr(app, "release", lambda *_: copy.deepcopy(canonical))
    operator.variables = lambda: copy.deepcopy(variables)
    original_git = operator.git
    operator.git = lambda *args: (
        args[-1].split("^{")[0]
        if args[0] == "rev-parse" and args[-1].endswith("^{commit}")
        else ""
        if args[0] == "fetch"
        else original_git(*args)
    )
    assert preflight.inspect(operator, NEW, OLD)["route"] in ("MANUAL", "BLOCKED")
    calls = 0

    def drift(*_):
        nonlocal calls
        calls += 1
        return {**canonical, "commit": OLD if calls == 1 else NEW}

    monkeypatch.setattr(app, "release", drift)
    with pytest.raises(app.Blocked, match="Production changed"):
        preflight.inspect(operator, NEW, OLD)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_database_version_is_bound_to_the_actual_open_argument(version):
    from types import SimpleNamespace

    operator = SimpleNamespace(git=lambda *_: schema_cases.writer_source(version))
    assert preflight.database_version(operator, NEW) == version


OPEN = "this.factory().open(scope ? `${LOCAL_DATABASE}.${scope}` : LOCAL_DATABASE, "


@pytest.mark.parametrize("changed", [
    OPEN + "2); records.slice(0, 1)",
    OPEN + "version); records.slice(0, 1)",
    OPEN + "1 + 1)",
    'this.factory()["open"](LOCAL_DATABASE, 3); factory.open(other, 1)',
    'this.factory()["open"](LOCAL_DATABASE, 3); this.factory().open(other, 1)',
    OPEN + '2); /* factory.open(other, 1) */',
    OPEN + '2); const text = "factory.open(other, 1)"',
    OPEN + '2); const text = `factory.open(other, 1)`',
    OPEN + '1); factory.open(other, 2)',
])
def test_unknown_actual_writer_cannot_borrow_an_unrelated_version_one(changed):
    from types import SimpleNamespace

    source = schema_cases.writer_source(1).replace(
        OPEN + "1)", changed
    )
    with pytest.raises(app.Blocked):
        preflight.database_version(SimpleNamespace(git=lambda *_: source), NEW)
