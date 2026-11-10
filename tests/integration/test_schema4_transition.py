"""Actual v2.2.2 calculations, read by the candidate without recalculation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from autonavlog.local import LocalApplication
from autonavlog.local_persistence import migrate_record

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/schema4"


def test_schema4_fixture_provenance():
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    assert provenance["commit"] == "03cc463cf09192e1403f839df4165410c5db8d7b"
    assert (provenance["app_version"], provenance["weather_version"]) == ("2.2.2", "0.5.0")
    for name, expected in provenance["files"].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("mode", ["ftd", "msm"])
@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("custom_name", [False, True])
def test_schema4_retains_work_and_historical_calculation(monkeypatch, mode, saved, custom_name):
    original = json.loads((FIXTURES / f"{mode}.json").read_text())
    if not saved:
        original["checkpoint"] = None
    projects = [original["draft"], original["checkpoint"], original["lastCalculation"]["project"]]
    if custom_name:
        for project in projects:
            if project:
                project["name"] = "Manually saved name"
    untouched = copy.deepcopy(original)
    record = migrate_record(original).model_dump(mode="json")
    model = "MSM" if mode == "msm" else None
    for before, after in zip(projects, [record["draft"], record["checkpoint"],
                                       record["lastCalculation"]["project"]], strict=True):
        if before is None:
            assert after is None
            continue
        assert after["schema_version"] == 5
        assert after["selected_forecast_model"] == model
        # Existing automatic-name migration is independent of forecast schema.
        expected = copy.deepcopy(before)
        expected.update(schema_version=5, selected_forecast_model=model)
        if not custom_name:
            prefix = "FTD_RJFM-RJFS" if mode == "ftd" else before["name"]
            assert after["name"].startswith(prefix + "_")
            assert after["metadata"]["project_name_format"] == 2
            expected["name"] = after["name"]
            expected["metadata"].update({key: after["metadata"][key] for key in (
                "project_name_format", "project_name_base", "project_name_generated")})
        assert after == expected
    assert record["draft"]["pilot_name"] == "unsaved draft"
    if saved:
        assert record["checkpoint"]["pilot_name"] != record["draft"]["pilot_name"]
    last = record["lastCalculation"]
    expected_outcome = copy.deepcopy(original["lastCalculation"]["outcome"])
    expected_outcome.update(selected_forecast_model=model, forecast_provenance={})
    for row in expected_outcome["display_rows"]:
        row["thirty_degree_cut_seconds"] = None
    assert last["outcome"] == expected_outcome
    for key in original["lastCalculation"].keys() - {"project", "outcome"}:
        assert last[key] == original["lastCalculation"][key]
    assert migrate_record(record).model_dump(mode="json") == record
    app = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    try:
        def forbidden(*args, **kwargs):
            raise AssertionError("restoration must not calculate")

        monkeypatch.setattr(app.session.calculation_service, "calculate", forbidden)
        restored = json.loads(app.dispatch("bootstrap", {
            "version": 1, "project": record["draft"], "last_calculation": last,
            "outcome": last["outcome"], "destination_wind": last["destination_wind"],
            "import_result": None, "import_filename": None,
        }))
        assert restored["workingRecovery"]["last_calculation"] == last
        assert restored["project"] == {**record["draft"], "status": "MANUAL_INPUT_REQUIRED"}
        assert not restored["readiness"]["calculationIsCurrent"]
        # Only explicit conflict resolution applies the existing stale-result cleanup.
        resolved = json.loads(app.dispatch("prepareSyncResolution", {"record": record}))
        assert resolved["lastCalculation"] is None
        assert record["lastCalculation"] == last
    finally:
        app.close()
    assert original == untouched
