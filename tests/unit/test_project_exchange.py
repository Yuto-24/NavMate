from __future__ import annotations

import json
from pathlib import Path

import pytest

from autonavlog.local import LocalApplication
from autonavlog.project_exchange import MAX_BYTES, export_project, import_project

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def app():
    local = LocalApplication(ROOT / "data")
    inputs = json.loads((ROOT / "tests/fixtures/issue_117_ftd.json").read_text())
    local.dispatch("importRoute", {"filename": "route.kml", "kml_text":
        (ROOT / "tests/fixtures/issue_43_golden.kml").read_text()})
    local.dispatch("confirmRoute", inputs["confirm"])
    yield local
    local.close()


def test_input_round_trip_and_recalculate_in_another_environment(app):
    original = app.session.project
    original.metadata["secret"] = {"token": "NEVER_EXPORT", "owner": "NEVER_EXPORT"}
    original.selected_forecast_run_id = "old-run"
    original.revision = 9
    text = export_project(original)
    assert "NEVER_EXPORT" not in text
    assert "old-run" not in text
    assert str(original.id) not in text
    restored = import_project(text)
    assert restored.id != original.id
    assert restored.revision == 0
    assert restored.selected_forecast_run_id is None
    assert export_project(restored) == text
    receiver = LocalApplication(ROOT / "data")
    try:
        state = json.loads(receiver.dispatch("bootstrap", {"version": 1,
            "project": restored.model_dump(mode="json"), "outcome": None,
            "destination_wind": None, "import_result": None, "import_filename": None}))
        assert state["outcome"] is None
        # Reconfirm readiness through the ordinary update path before calculation.
        inputs = json.loads((ROOT / "tests/fixtures/issue_117_ftd.json").read_text())["confirm"]
        update = {key: value for key, value in inputs.items() if key in {
            "flight_date", "departure_time_jst", "weather_mode", "ftd_weather",
            "default_variation_deg_east", "total_usable_fuel_gal", "defaults_confirmed"}}
        update["total_usable_fuel_gal"] = 90
        update["defaults_confirmed"] = True
        receiver.dispatch("updateProject", update)
        calculated = json.loads(receiver.dispatch("calculate"))
        assert calculated["outcome"]["project_id"] == str(restored.id)
        assert calculated["readiness"]["calculationIsCurrent"]
    finally:
        receiver.close()


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(version=2),
    lambda d: d.update(version=True),
    lambda d: d.update(format="autonavlog.navlog"),
    lambda d: d["inputs"].update(id="source-id"),
    lambda d: d["inputs"].pop("name"),
    lambda d: d["inputs"]["sections"][0].pop("id"),
    lambda d: d["inputs"]["sections"][0].pop("manual_wind_by_phase"),
    lambda d: d["inputs"]["sections"][0].pop("manual_tas_kt_by_phase"),
    lambda d: d["inputs"].update(total_usable_fuel_gal="90"),
    lambda d: d["inputs"].update(run_up_included=1),
    lambda d: d["inputs"].update(total_usable_fuel_gal=201),
    lambda d: d["inputs"].update(tgl_count=21),
    lambda d: d["inputs"]["sections"][0].update(planned_altitude_ft_msl=-100),
    lambda d: d["inputs"]["sections"][0].update(manual_temperature_c=100),
    lambda d: d["inputs"]["route_nodes"].append(d["inputs"]["route_nodes"][0]),
    lambda d: d["inputs"]["sections"][0].update(to_node_id="00000000-0000-0000-0000-000000000000"),
    lambda d: d["inputs"]["route_nodes"][0].update(latitude_deg=91),
    lambda d: d["inputs"]["sections"][0].update(planned_altitude_ft_msl=float("nan")),
    lambda d: d["planning"].update(calculated_against_fingerprint="0" * 64),
    lambda d: d["manual_sea"].update(unknown=3000),
    lambda d: d["inputs"].update(name="x" * 4097),
])
def test_invalid_input_is_rejected_without_mutating_work(app, mutation):
    before = app.session.project.model_dump(mode="json")
    payload = json.loads(export_project(app.session.project))
    mutation(payload)
    response = json.loads(app.dispatch_response(
        "prepareProjectImport", {"text": json.dumps(payload)}
    ))
    assert response["error"]["code"] == "PROJECT_JSON_INVALID"
    assert app.session.project.model_dump(mode="json") == before


@pytest.mark.parametrize("text", ["{", "[]", '{"version":1,"version":1}', " " * (MAX_BYTES + 1)])
def test_bad_json_and_size(text):
    with pytest.raises(ValueError):
        import_project(text)


def test_legacy_sea_keys_import_without_adopting_old_terrain(app):
    from autonavlog.application.sea import LEGACY_POLICY, legacy_interval_keys, sea_plan

    project = app.session.project
    old_key, new_key = next(iter(legacy_interval_keys(project).items()))
    project.metadata["sea"] = {"policy": LEGACY_POLICY, "records": {
        old_key: {"manual_ft": 6000, "terrain": {"complete": True, "required": 1,
            "valid": 1, "maximum_m": 304.8}}
    }}
    payload = json.loads(export_project(project))
    assert payload["manual_sea"] == {new_key: 6000}
    payload["manual_sea"] = {old_key: 6000}  # An unmodified v1 export from the prior release.
    item = sea_plan(import_project(json.dumps(payload)))["intervals"][0]
    assert item["manual_ft"] == 6000 and item["automatic_ft"] is None
    payload["manual_sea"][new_key] = 7000
    with pytest.raises(ValueError, match="duplicate manual SEA"):
        import_project(json.dumps(payload))


def test_checkpoints_manual_sea_and_stale_inputs_survive_without_calculation(app):
    from autonavlog.application.sea import POLICY, sea_plan

    project = app.session.project
    section = project.sections[0]
    app.dispatch("replaceCheckPoints", {"check_points": [{
        "name": "ridge", "latitude_deg": 32.0, "longitude_deg": 131.0,
        "linked_section_id": str(section.id),
    }]})
    project = app.session.project
    plan = sea_plan(project)
    key = next(item["key"] for item in plan["intervals"] if item["geometry_valid"])
    project.metadata["sea"] = {"policy": POLICY, "records": {
        key: {"manual_ft": 6000, "terrain": {"complete": True, "maximum_m": 100,
            "provenance": [{"token": "DO_NOT_TRANSFER"}]}}
    }}
    project.metadata["ui_state"]["calculated_against_fingerprint"] = "0" * 64
    project.pilot_name = "edited after calculation"
    text = export_project(project)
    assert "DO_NOT_TRANSFER" not in text
    assert "calculated_against_fingerprint" not in text
    restored = import_project(text)
    assert restored.pilot_name == "edited after calculation"
    assert restored.visual_references == project.visual_references
    assert json.loads(text)["manual_sea"] == {key: 6000}
    restored_plan = sea_plan(restored)
    interval = next(item for item in restored_plan["intervals"] if item["key"] == key)
    assert interval["manual_ft"] == 6000
    assert interval["automatic_ft"] is None
    payload = json.loads(text)
    payload["inputs"]["visual_references"].append(payload["inputs"]["visual_references"][0])
    with pytest.raises(ValueError, match="duplicate"):
        import_project(json.dumps(payload))


def test_missing_checkpoint_identity_is_not_generated(app):
    app.dispatch("replaceCheckPoints", {"check_points": [{
        "name": "CP", "latitude_deg": 32.0, "longitude_deg": 131.0,
        "linked_section_id": str(app.session.project.sections[0].id),
    }]})
    payload = json.loads(export_project(app.session.project))
    del payload["inputs"]["visual_references"][0]["id"]
    with pytest.raises(ValueError, match="nested Project input"):
        import_project(json.dumps(payload))
