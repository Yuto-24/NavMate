from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from autonavlog.local import LocalApplication

ROOT = Path(__file__).resolve().parents[2]
INPUTS = json.loads((ROOT / "tests/fixtures/issue_117_ftd.json").read_text())


@pytest.fixture
def local():
    application = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    yield application
    application.close()


def calculate(local, *, forecast=False, rounding_mode=True):
    inputs = json.loads(json.dumps(INPUTS))
    if forecast:
        inputs["confirm"].update(
            weather_mode="FORECAST", flight_date="2026-09-12", departure_time_jst="12:00"
        )
    local.dispatch(
        "importRoute",
        {
            "filename": "issue_43_golden.kml",
            "kml_text": (ROOT / "tests/fixtures/issue_43_golden.kml").read_text(),
        },
    )
    state = json.loads(local.dispatch("confirmRoute", inputs["confirm"]))
    project = state["project"]
    update = {
        **{
            key: inputs["confirm"][key]
            for key in (
                "flight_date",
                "departure_time_jst",
                "weather_mode",
                "ftd_weather",
                "default_variation_deg_east",
            )
        },
        "total_usable_fuel_gal": 90,
        "sections": [
            {
                "section_id": section["id"],
                "phase": section["phase"],
                "planned_altitude_ft_msl": altitude,
            }
            for section, altitude in zip(project["sections"], inputs["altitudes"], strict=True)
        ],
        "visual_reporting_point_node_id": project["route_nodes"][-2]["id"],
        "selected_pattern_altitude_ft_msl": 1000,
    }
    local.dispatch("updateProject", update)
    return json.loads(local.dispatch("calculate", {"rounding_mode": rounding_mode}))


def test_local_ftd_golden_and_failed_calculation_preserves_last_good(local, monkeypatch):
    state = calculate(local, rounding_mode=False)
    golden = json.loads((ROOT / "tests/fixtures/issue_117_ftd_golden.json").read_text())
    outcome = state["outcome"]
    assert state["savedProjects"] == []
    assert state["readiness"]["calculationIsCurrent"]
    assert state["readiness"]["issues"] == []
    assert len(state["project"]["sections"]) == 4
    assert [point["type"] for point in outcome["derived_points"]] == ["RCA", "EOC"]
    assert outcome["summary"] == golden["summary"]
    assert outcome["fuel_plan"] == pytest.approx(golden["fuel"], abs=1e-8, rel=0)
    assert len(outcome["sections"]) == len(golden["zones"])
    for actual, expected in zip(outcome["sections"], golden["zones"], strict=True):
        for key, value in expected.items():
            if isinstance(value, dict) and "value" in value:
                adopted = actual[key]
                assert adopted["automatic_value"] == pytest.approx(value["value"], abs=1e-8, rel=0)
                assert adopted["automatic_status"] == value["status"]
            elif isinstance(value, (int, float)):
                assert actual[key] == pytest.approx(value, abs=1e-8, rel=0)
            else:
                assert actual[key] == value

    previous = local.session.outcome

    def fail(*args, **kwargs):
        raise RuntimeError("calculation failure")

    monkeypatch.setattr(local.session.calculation_service, "calculate", fail)
    with pytest.raises(RuntimeError, match="calculation failure"):
        local.dispatch("calculate")
    assert local.session.outcome is previous


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/projects/save", {"name": "unsupported"}),
        ("importRoute", {"filename": "route.kmz", "content_base64": "bm90IGEgemlw"}),
        ("importRoute", {"filename": "route.kml", "kml_text": "<broken"}),
        ("calculate", {}),
    ],
)
def test_local_fails_closed(local, path, payload):
    with pytest.raises(ValueError):
        local.dispatch(path, payload)
    assert local.session.project is None


def test_new_local_instance_does_not_restore_project(local):
    calculate(local)
    another = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    try:
        state = json.loads(another.dispatch("bootstrap"))
        assert state["project"] is None
        assert state["outcome"] is None
        assert state["savedProjects"] == []
    finally:
        another.close()


def test_local_forecast_uses_actual_fixture_without_network(local, monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("Local Calculation must not fetch weather")

    monkeypatch.setattr("urllib.request.urlopen", fail_network)
    state = calculate(local, forecast=True)
    assert state["outcome"]["selected_forecast_run_id"] == "20260912030000"
    assert state["outcome"]["status"] == "READY_FOR_COPY"
    assert state["outcome"]["summary"]["time"]["text"] == "0:50"
    assert state["outcome"]["summary"]["distance"]["text"] == "125.5"
    assert state["readiness"]["calculationIsCurrent"]
    assert state["savedProjects"] == []
    assert state["outcome"]["display_rows"][-2]["wind"]["reason_code"] == "TAF_PROXY_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "operation,payload,code",
    [
        ("calculate", {}, "PROJECT_REQUIRED"),
        ("confirmRoute", {}, "VALIDATION_FAILED"),
        ("renameRouteNode", {"node_id": "invalid", "name": "test"}, "VALIDATION_FAILED"),
        ("importRoute", {"filename": "a.kml", "kml_text": "<broken"}, "KML_IMPORT_FAILED"),
        ("importRoute", {"filename": "a.kml", "content_base64": "!!"}, "UPLOAD_ENCODING_INVALID"),
        (
            "importRoute",
            {"filename": "a.kmz", "content_base64": "bm90IGEgemlw"},
            "KML_IMPORT_FAILED",
        ),
    ],
)
def test_local_error_response_preserves_application_meaning(local, operation, payload, code):
    error = json.loads(local.dispatch_response(operation, payload))["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert error["message"]
    assert "Traceback" not in error["message"]
    if code == "VALIDATION_FAILED":
        assert error["message"] == "入力内容を確認してください。"
        issues = error["details"]["issues"]
        if operation == "renameRouteNode":
            assert len(issues) == 1
            assert set(issues[0]) == {"location", "message", "type"}
            assert issues[0]["location"] == ["node_id"]
            assert issues[0]["type"] == "uuid_parsing"
            assert issues[0]["message"].startswith("Input should be a valid UUID")
        else:
            assert issues == [
                {"location": [field], "message": "Field required", "type": "missing"}
                for field in (
                    "candidate_kind", "route_use_confirmed", "flight_date", "departure_time_jst"
                )
            ]
    else:
        assert error["message"] == {
            "PROJECT_REQUIRED": "先に経路を確定してください。",
            "KML_IMPORT_FAILED": (
                "KMZアーカイブが不正です。" if payload.get("filename") == "a.kmz"
                else "KMLドキュメントが不正または安全ではありません。"
            ),
            "UPLOAD_ENCODING_INVALID": "アップロード内容を読み取れません。",
        }[code]
        assert error["details"] == {}
    assert local.session.project is None


def test_local_operations_keep_draft_last_good_and_failed_transaction(local, monkeypatch):
    state = calculate(local)
    project = local.session.project
    node = state["project"]["route_nodes"][1]
    renamed = json.loads(
        local.dispatch_response(
            "renameRouteNode",
            {
                "node_id": node["id"],
                "name": "renamed",
            },
        )
    )
    assert renamed["project"]["route_nodes"][1]["name"] == "renamed"
    assert renamed["outcome"] is not None
    local.dispatch_response("acknowledge", {"key": "test/key", "checked": True})
    local.dispatch_response("replaceCheckPoints", {"check_points": []})
    # The facade commits the valid draft before calculation; failure retains it and last-good.
    before_outcome = local.session.outcome.model_dump(mode="json")
    update = {
        "flight_date": "2026-09-11",
        "departure_time_jst": "09:00",
        "total_usable_fuel_gal": 75,
        "default_variation_deg_east": 8,
        "weather_mode": "FTD",
        "ftd_weather": project.ftd_weather.model_dump(mode="json"),
    }

    def fail(*args, **kwargs):
        raise RuntimeError("calculation failure")

    monkeypatch.setattr(local.session.calculation_service, "calculate", fail)
    error = json.loads(local.dispatch_response("updateAndRecalculate", update))["error"]
    assert error == {"code": "REQUEST_FAILED", "message": "処理に失敗しました。", "details": {}}
    assert local.session.project.total_usable_fuel_gal == 75
    after_outcome = local.session.outcome.model_dump(mode="json")
    # Readiness reclassifies stale status; canonical calculation values remain unchanged.
    for key in before_outcome.keys() - {"status"}:
        assert after_outcome[key] == before_outcome[key]
    assert local.session.outcome is not None
    # A plain update commits its draft, preserving the previous result for stale display.
    draft = json.loads(local.dispatch_response("updateProject", update))
    assert draft["project"]["total_usable_fuel_gal"] == 75
    assert draft["outcome"] is not None
    assert not draft["readiness"]["calculationIsCurrent"]


@pytest.mark.parametrize("operation", ["calculate", "updateAndRecalculate"])
@pytest.mark.parametrize("failure", ["validation", "runtime"])
def test_internal_failure_semantics_preserve_local_draft_and_last_good(
    local, monkeypatch, operation, failure
):
    from pydantic import BaseModel

    calculate(local)
    old_outcome = local.session.outcome.model_dump(mode="json")
    update = {
        "flight_date": "2026-09-11",
        "departure_time_jst": "09:00",
        "total_usable_fuel_gal": 75,
        "default_variation_deg_east": 8,
        "weather_mode": "FTD",
        "ftd_weather": local.session.project.ftd_weather.model_dump(mode="json"),
    }

    class InternalResult(BaseModel):
        internal_count: int

    def fail(*args, **kwargs):
        if failure == "validation":
            InternalResult.model_validate({"internal_count": "secret internal detail"})
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(local.session.calculation_service, "calculate", fail)
    request_body = update if operation == "updateAndRecalculate" else {}
    error = json.loads(local.dispatch_response(operation, request_body))["error"]
    assert error == {
        "code": "CALCULATION_JOB_FAILED" if operation == "calculate" else "REQUEST_FAILED",
        "message": "計算に失敗しました。" if operation == "calculate" else "処理に失敗しました。",
        "details": {},
    }
    assert "secret" not in json.dumps(error)
    assert error["code"] != "VALIDATION_FAILED"
    assert local.session.project.total_usable_fuel_gal == (
        75 if operation == "updateAndRecalculate" else 90
    )
    after = local.session.outcome.model_dump(mode="json")
    for key in old_outcome.keys() - {"status"}:
        assert after[key] == old_outcome[key]


def test_reload_working_recovery_restores_import_and_last_good_without_calculation(
    local, monkeypatch
):
    imported = json.loads(
        local.dispatch(
            "importRoute",
            {
                "filename": "route.kml",
                "kml_text": (ROOT / "tests/fixtures/issue_43_golden.kml").read_text(),
            },
        )
    )
    replacement = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    try:
        restored = json.loads(replacement.dispatch("bootstrap", imported["workingRecovery"]))
        assert restored["import"] == imported["import"]
        confirmed = json.loads(replacement.dispatch("confirmRoute", INPUTS["confirm"]))
        assert confirmed["project"]
    finally:
        replacement.close()

    calculated = calculate(local)
    replacement = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    try:

        def forbidden(*args, **kwargs):
            raise AssertionError("reload must never calculate")

        monkeypatch.setattr(replacement.app, "calculate", forbidden)
        restored = json.loads(replacement.dispatch("bootstrap", calculated["workingRecovery"]))
        assert restored["project"] == calculated["project"]
        assert restored["outcome"] == calculated["outcome"]
        assert restored["readiness"] == calculated["readiness"]
        assert restored["savedProjects"] == []
    finally:
        replacement.close()


def test_recovery_rejects_last_good_from_another_project(local):
    from uuid import uuid4

    state = calculate(local)
    state["workingRecovery"]["outcome"]["project_id"] = str(uuid4())
    result = json.loads(local.dispatch_response("bootstrap", state["workingRecovery"]))
    assert result["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("forecast", [False, True])
def test_durable_record_load_keeps_original_calculation_and_run(local, monkeypatch, forecast):
    from uuid import uuid4

    from autonavlog.local_persistence import migrate_record

    calculated = calculate(local, forecast=forecast)
    working = calculated["workingRecovery"]
    last = working["last_calculation"]
    assert last is not None
    draft = dict(working["project"])
    draft["total_usable_fuel_gal"] = 73
    record = migrate_record(
        {
            "schemaVersion": 2,
            "id": draft["id"],
            "token": str(uuid4()),
            "draft": draft,
            "checkpoint": working["project"],
            "lastCalculation": last,
            "updatedAt": draft["updated_at"],
        }
    ).model_dump(mode="json")
    assert "web_owner_id" not in record["draft"]["metadata"]
    assert "web_owner_id" not in record["lastCalculation"]["project"]["metadata"]
    with_local = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    try:

        def unexpected_calculation(*args, **kwargs):
            raise AssertionError("opening durable data must not calculate")

        monkeypatch.setattr(
            with_local.session.calculation_service, "calculate", unexpected_calculation
        )
        restored = json.loads(
            with_local.dispatch(
                "bootstrap",
                {
                    "version": 1,
                    "project": record["draft"],
                    "last_calculation": record["lastCalculation"],
                    "outcome": last["outcome"],
                    "destination_wind": last["destination_wind"],
                    "import_result": None,
                    "import_filename": None,
                },
            )
        )
        assert restored["workingRecovery"]["last_calculation"] == last
        assert restored["project"]["selected_forecast_run_id"] == draft["selected_forecast_run_id"]
        assert restored["project"]["total_usable_fuel_gal"] == 73
        assert restored["outcome"] is not None
        assert not restored["readiness"]["calculationIsCurrent"]
    finally:
        with_local.close()


def test_local_kmz_uses_shared_importer_and_preserves_document_selection(local):
    kml = (ROOT / "tests/fixtures/issue_43_golden.kml").read_bytes()
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("one.kml", kml)
        archive.writestr("folder/two.kml", kml)
    request = {
        "filename": "routes.kmz",
        "content_base64": base64.b64encode(buffer.getvalue()).decode(),
    }
    error = json.loads(local.dispatch_response("importRoute", request))["error"]
    assert error["code"] == "KMZ_DOCUMENT_SELECTION_REQUIRED"
    assert set(error["details"]["candidates"]) == {"one.kml", "folder/two.kml"}
    selected = json.loads(
        local.dispatch("importRoute", {**request, "kmz_kml_filename": "folder/two.kml"})
    )
    plain = json.loads(
        local.dispatch("importRoute", {"filename": "route.kml", "kml_text": kml.decode()})
    )
    assert selected["import"]["candidates"] == plain["import"]["candidates"]
    invalid = json.loads(
        local.dispatch_response("importRoute", {**request, "kmz_kml_filename": "missing.kml"})
    )
    assert invalid["error"]["code"] == "KML_IMPORT_FAILED"
    assert json.loads(local.dispatch("bootstrap"))["import"] == plain["import"]


def test_browser_taf_records_reuse_selection_and_do_not_change_navigation(local):
    from datetime import datetime

    baseline = calculate(local, forecast=True)
    assert local.destination_taf_airport("calculate", {}) == "RJFS"
    eta = datetime.fromisoformat(baseline["destinationWind"]["valid_time_utc"]).timestamp()
    records = [{"icaoId": "RJFS", "mostRecent": 1, "validTimeFrom": eta - 3600,
                "validTimeTo": eta + 3600, "rawTAF": "TAF RJFS", "fcsts": [
                    {"timeFrom": eta - 3600, "timeTo": eta + 3600, "wdir": 240, "wspd": 18},
                    {"timeFrom": eta - 3600, "timeTo": eta + 3600, "fcstChange": "TEMPO",
                     "wdir": 90, "wspd": 40}]}]
    local.set_destination_taf({"records": records, "reason_code": None})
    available = json.loads(local.dispatch("calculate"))
    assert available["destinationWind"]["wind_speed_kt"] == 18
    assert available["destinationWind"]["availability"] == "AVAILABLE"
    for reason in ["TAF_FETCH_FAILED", "TAF_FETCH_TIMEOUT", "TAF_PROXY_NOT_CONFIGURED"]:
        assert local.destination_taf_airport("calculate", {}) == "RJFS"
        local.set_destination_taf({"records": [], "reason_code": reason})
        failed = json.loads(local.dispatch("calculate"))
        assert failed["destinationWind"]["availability"] == "UNAVAILABLE"
        assert failed["destinationWind"]["reason_code"] == reason
        assert failed["project"] == available["project"]
        last_wind = failed["workingRecovery"]["last_calculation"]["destination_wind"]
        assert last_wind["reason_code"] == reason
        for section, expected in zip(
            failed["outcome"]["sections"], available["outcome"]["sections"], strict=True
        ):
            for key, value in section.items():
                if isinstance(value, dict) and "automatic_value" in value:
                    assert value["automatic_value"] == expected[key]["automatic_value"]
                    assert value["manual_override"] == expected[key]["manual_override"]
                else:
                    assert value == expected[key]
        for key in ["fuel_plan", "summary", "status"]:
            assert failed["outcome"][key] == available["outcome"][key]
        assert failed["readiness"]["calculationIsCurrent"]
    # Records cannot leak into the next acquisition, and FTD/non-calculation never fetch.
    assert local.destination_taf_airport("updateAndRecalculate", {"weather_mode": "FTD"}) is None
    assert local.destination_taf_airport("saveProject", {}) is None
    assert local.destination_taf_airport("calculate", {}) == "RJFS"
    reset = json.loads(local.dispatch("calculate"))
    assert reset["destinationWind"]["reason_code"] == "TAF_PROXY_NOT_CONFIGURED"


def test_sync_resolution_retains_only_matching_calculation_and_reidentifies_copy(local):
    from copy import deepcopy
    from uuid import uuid4

    state = calculate(local)
    working = state["workingRecovery"]
    record = {
        "schemaVersion": 2,
        "id": working["project"]["id"],
        "token": str(uuid4()),
        "checkpoint": deepcopy(working["project"]),
        "draft": deepcopy(working["project"]),
        "lastCalculation": working["last_calculation"],
        "updatedAt": working["project"]["updated_at"],
    }
    valid = json.loads(local.dispatch("prepareSyncResolution", {"record": record}))
    assert valid["lastCalculation"] is not None
    copy_id = str(uuid4())
    copied = json.loads(
        local.dispatch("prepareSyncResolution", {"record": record, "copy_id": copy_id})
    )
    assert copied["id"] == copied["draft"]["id"] == copied["checkpoint"]["id"] == copy_id
    assert copied["draft"]["revision"] == copied["checkpoint"]["revision"] == 0
    last = copied["lastCalculation"]
    assert last["project"]["id"] == last["outcome"]["project_id"] == copy_id
    assert last["calculation_fingerprint"] == record["lastCalculation"]["calculation_fingerprint"]
    stale = deepcopy(record)
    stale["draft"]["total_usable_fuel_gal"] += 5
    rejected = json.loads(
        local.dispatch("prepareSyncResolution", {"record": stale, "copy_id": copy_id})
    )
    assert rejected["lastCalculation"] is None
    assert record["lastCalculation"] is not None


def test_new_work_replaces_all_mutable_state_and_preserves_recovery(local):
    calculated = calculate(local)
    working = calculated["workingRecovery"]
    old_app, old_session = local.app, local.session
    old_storage = Path(local._temporary.name)
    for _ in range(3):
        state = json.loads(local.dispatch("newWork"))
        assert state["project"] is None
        assert state["outcome"] is None
        assert not state["import"]["candidates"]
        assert state["workingRecovery"]["last_calculation"] is None
        assert local.app is not old_app
        assert local.session is not old_session
        assert not old_storage.exists()
        restored = json.loads(local.dispatch("bootstrap", working))
        assert restored["project"]["id"] == calculated["project"]["id"]
        assert restored["workingRecovery"]["last_calculation"] == working["last_calculation"]
        old_app, old_session = local.app, local.session
        old_storage = Path(local._temporary.name)


def test_new_work_replaces_forecast_and_destination_taf_state():
    local = LocalApplication(ROOT / "data")
    try:
        old_weather = local.local_weather
        old_provider = local.app.destination_wind_provider
        old_service = local.session.calculation_service
        local.dispatch("newWork")
        assert local.local_weather is not old_weather
        assert local.app.destination_wind_provider is not old_provider
        assert local.session.calculation_service is not old_service
        assert not local.requires_weather()
    finally:
        local.close()


def test_failed_new_work_construction_keeps_previous_work(local, monkeypatch):
    import autonavlog.local as module

    local.dispatch("importRoute", {
        "filename": "previous.kml",
        "kml_text": (ROOT / "tests/fixtures/issue_43_golden.kml").read_text(),
    })
    before = json.loads(local.dispatch("state"))
    storage = Path(local._temporary.name)

    def failed(*args, **kwargs):
        raise RuntimeError("initialization failed")

    monkeypatch.setattr(module, "LocalApplication", failed)
    assert json.loads(local.dispatch_response("newWork"))["error"]["code"] == "REQUEST_FAILED"
    assert storage.exists()
    assert json.loads(local.dispatch("state")) == before


@pytest.mark.parametrize("failure", ["presentation", "serialization"])
def test_failed_new_work_response_keeps_previous_work(local, monkeypatch, failure):
    import autonavlog.local as module

    calculated = calculate(local)
    before = local.dispatch("state")
    old_app, old_session, old_weather = local.app, local.session, local.local_weather
    storage = Path(local._temporary.name)
    sentinel = storage / "previous-work.txt"
    sentinel.write_text("previous work")
    replacements = []

    def replacement(*args, **kwargs):
        candidate = LocalApplication(*args, **kwargs)
        replacements.append(candidate)
        present = candidate.app.present

        def failed(session):
            if failure == "presentation":
                raise RuntimeError("presentation failed")
            state = present(session)
            state["unserializable"] = object()
            return state

        monkeypatch.setattr(candidate.app, "present", failed)
        return candidate

    monkeypatch.setattr(module, "LocalApplication", replacement)
    assert json.loads(local.dispatch_response("newWork"))["error"]["code"] == "REQUEST_FAILED"
    assert local.app is old_app
    assert local.session is old_session
    assert local.local_weather is old_weather
    assert sentinel.read_text() == "previous work"
    assert local.dispatch("state") == before
    assert not Path(replacements[0]._temporary.name).exists()
    assert json.loads(local.dispatch("calculate"))["outcome"] == calculated["outcome"]


@pytest.mark.parametrize("forecast", [False, True], ids=["ftd", "forecast"])
def test_rounding_mode_uses_common_calculation_wind_and_only_projects_toat(local, forecast):
    from autonavlog.domain.project import ManualWind
    from autonavlog.nav.wind_triangle import solve_wind_triangle

    calculate(local, forecast=forecast)
    invalid = json.loads(local.dispatch_response("calculate", {"rounding_mode": "ON"}))
    assert invalid["error"] == {
        "code": "VALIDATION_FAILED",
        "message": "入力内容を確認してください。",
        "details": {"issues": [{
            "location": ["rounding_mode"],
            "message": "Input should be a valid boolean",
            "type": "bool_type",
        }]},
    }
    project = local.session.project
    first = project.sections[0]
    first.manual_wind_by_phase[first.phase] = ManualWind(direction_deg_from=355, speed_kt=21)
    first.manual_temperature_c_by_phase[first.phase] = -1.5
    raw_inputs = project.model_dump(mode="json")
    off = json.loads(local.dispatch("calculate", {"rounding_mode": False}))
    rounded = json.loads(local.dispatch("calculate", {"rounding_mode": True}))
    assert rounded["roundingMode"] is True
    assert "rounding_mode" not in rounded["project"]
    assert rounded["readiness"]["calculationIsCurrent"]
    assert local.session.project.sections[0].model_dump() == first.model_dump()
    assert rounded["project"]["ftd_weather"] == raw_inputs["ftd_weather"]
    assert rounded["project"]["sections"] == raw_inputs["sections"]

    def adopted(value):
        return (
            value["manual_override"]
            if value["adopted_source"] == "MANUAL"
            else value["automatic_value"]
        )

    for zone in rounded["outcome"]["sections"]:
        direction = adopted(zone["wind_direction_deg_from"])
        speed = adopted(zone["wind_speed_kt"])
        assert direction is None or direction % 10 == 0
        if speed is None:
            continue
        result = solve_wind_triangle(
            adopted(zone["true_course_deg"]), adopted(zone["tas_kt"]), direction, speed
        )
        assert adopted(zone["ground_speed_kt"]) == pytest.approx(result.ground_speed_kt)
        assert adopted(zone["wca_deg"]) == pytest.approx(result.wca_deg)
        assert adopted(zone["magnetic_heading_deg"]) == pytest.approx(
            (adopted(zone["magnetic_course_deg"]) + result.wca_deg) % 360
        )
        assert zone["wind_direction_deg_from"]["automatic_metadata"]["rounding_mode"] is True
    assert adopted(rounded["outcome"]["sections"][0]["wind_direction_deg_from"]) == 0
    assert adopted(rounded["outcome"]["sections"][0]["temperature_c"]) == -1.5
    assert (
        rounded["outcome"]["sections"][0]["ground_speed_kt"]
        != off["outcome"]["sections"][0]["ground_speed_kt"]
    )
    toat = [
        row["toat"] for row in rounded["outcome"]["display_rows"] if row["toat"]["text"] is not None
    ]
    assert any(cell["text"] == "-2" and cell["effective_value"] == -1.5 for cell in toat)
    assert all(
        "." not in cell["text"]
        for cell in toat
        if isinstance(cell["effective_value"], (int, float))
    )
    assert (
        json.loads(local.dispatch("calculate", {"rounding_mode": False}))["outcome"]
        == off["outcome"]
    )


def test_rounding_failure_is_atomic_and_reload_resets_without_relabeling_result(local, monkeypatch):
    calculate(local)
    rounded = json.loads(local.dispatch("calculate", {"rounding_mode": True}))
    original_calculate = local.session.calculation_service.calculate

    def fail(*args, **kwargs):
        raise ValueError("injected rounding calculation failure")

    monkeypatch.setattr(local.session.calculation_service, "calculate", fail)
    assert "error" in json.loads(local.dispatch_response("calculate", {"rounding_mode": False}))
    retained = json.loads(local.dispatch("state"))
    assert retained["roundingMode"] is True
    assert retained["outcome"] == rounded["outcome"]
    monkeypatch.setattr(local.session.calculation_service, "calculate", original_calculate)
    # The ordinary save refresh remains in the current work; it is not a reload.
    saved = json.loads(
        local.dispatch(
            "refreshSavedWork",
            {
                "working": retained["workingRecovery"],
                "rounding_mode": True,
            },
        )
    )
    assert saved["roundingMode"] is True and saved["outcome"] == rounded["outcome"]
    restored = json.loads(local.dispatch("bootstrap", saved["workingRecovery"]))
    assert restored["roundingMode"] is True
    assert restored["outcome"] == rounded["outcome"]
    # Restoring a normal-mode result resets the preference without relabeling it.
    normal = json.loads(local.dispatch("calculate", {"rounding_mode": False}))
    restored = json.loads(local.dispatch("bootstrap", normal["workingRecovery"]))
    assert restored["roundingMode"] is True
    assert restored["outcome"] is None
    assert restored["workingRecovery"]["last_calculation"] is None
    assert not restored["readiness"]["calculationIsCurrent"]
    assert restored["project"]["sections"] == saved["project"]["sections"]


@pytest.mark.parametrize("rounded", [False, True])
def test_empty_blocker_restore_retains_only_rounded_last_good(local, rounded):
    from autonavlog.domain.calculation import Issue

    calculate(local, rounding_mode=rounded)
    last = local.session.last_calculation.model_dump(mode="json")
    local.session.outcome = local.session.outcome.model_copy(update={
        "sections": [], "display_rows": [],
        "issues": [Issue(code="WEATHER_UNAVAILABLE", severity="BLOCKER", message="No weather")],
    })
    recovery = local.app.present(local.session)["workingRecovery"]
    restored = json.loads(local.dispatch("bootstrap", recovery))
    assert restored["roundingMode"] is True
    assert restored["workingRecovery"]["last_calculation"] == (last if rounded else None)
    assert restored["workingRecovery"]["outcome"]["sections"] == []
    assert restored["outcome"]["sections"] == (last["outcome"]["sections"] if rounded else [])
    assert any(issue["code"] == "WEATHER_UNAVAILABLE" for issue in restored["outcome"]["issues"])


@pytest.mark.parametrize("blocker_count", [1, 4])
def test_blocker_during_mode_transition_keeps_previous_mode_and_result(
    local, monkeypatch, blocker_count
):
    from autonavlog.domain.calculation import Issue
    from autonavlog.domain.enums import IssueSeverity

    calculate(local)
    previous = json.loads(local.dispatch("calculate", {"rounding_mode": False}))
    messages = [f"blocked wind triangle {index + 1}" for index in range(blocker_count)]
    blocked = local.session.outcome.model_copy(
        update={
            "issues": [
                Issue(
                    code="WIND_TRIANGLE_FAILED",
                    severity=IssueSeverity.BLOCKER,
                    message=message,
                )
                for message in messages
            ]
        }
    )
    monkeypatch.setattr(local.app, "_calculate_outcome", lambda *args, **kwargs: (blocked, None))
    failed = json.loads(local.dispatch_response("calculate", {"rounding_mode": True}))
    assert failed["error"]["code"] == "CALCULATION_FAILED"
    assert failed["error"]["message"] == "計算に失敗しました。" + " / ".join(messages[:3])
    current = json.loads(local.dispatch("state"))
    assert current["roundingMode"] is False
    assert current["outcome"] == previous["outcome"]


def _portable_calculation(application, feed, catalog, options=None):
    application.begin_weather()
    for _ in range(20):
        result = json.loads(application.dispatch_response("calculate", options))
        if "weather_request" not in result:
            return result
        request = result["weather_request"]
        assert request["model"] == "MSM"
        if request["kind"] == "catalog":
            assert application.weather_catalog("MSM", json.dumps(catalog)) == "{}"
        else:
            asset = request["asset"]
            assert application.accept_weather(
                "MSM", (feed / asset["file"]).read_bytes(), asset["sha256"]
            ) == "{}"
    pytest.fail("portable calculation did not converge")


def test_unprepared_weather_preflight_keeps_last_good_stale():
    from datetime import UTC, datetime, timedelta

    fixture = ROOT / "tests/fixtures/msm-portable"
    application = LocalApplication(ROOT / "data")
    try:
        before = calculate(application)
        draft = json.loads(application.dispatch("updateProject", {
            "weather_mode": "FORECAST", "flight_date": "2026-09-16",
            "departure_time_jst": "18:00",
            "total_usable_fuel_gal": before["project"]["total_usable_fuel_gal"],
            "default_variation_deg_east": before["project"]["default_variation_deg_east"],
        }))
        assert not draft["readiness"]["calculationIsCurrent"]
        catalog = json.loads((fixture / "catalog.json").read_text())
        now = datetime.now(UTC)
        catalog.update(generated_at=now.isoformat(),
                       expires_at=(now + timedelta(hours=1)).isoformat())
        result = _portable_calculation(application, fixture, catalog)
        assert result["error"]["code"] == "WEATHER_PREPARED_UNAVAILABLE"
        after = json.loads(application.dispatch("bootstrap"))
        assert not after["readiness"]["calculationIsCurrent"]
        assert after["project"]["weather_mode"] == "FORECAST"
        for key in before["outcome"].keys() - {"status"}:
            assert after["outcome"][key] == before["outcome"][key]
    finally:
        application.close()


def _pin_old_forecast(local):
    calculate(local, forecast=True)
    local.session.project.selected_forecast_run_id = "20260912000000"
    local.session.last_calculation = None
    return json.loads(local.dispatch("calculate"))


def _assert_forecast_snapshot(state, run):
    assert state["project"]["selected_forecast_run_id"] == run
    assert state["outcome"]["selected_forecast_run_id"] == run
    last = state["workingRecovery"]["last_calculation"]
    assert last["project"]["selected_forecast_run_id"] == run
    assert last["outcome"]["selected_forecast_run_id"] == run
    assert last["forecast_metadata"]["forecast_run_id"] == run
    assert state["readiness"]["calculationIsCurrent"]
    return last


def test_unchanged_success_refreshes_once_including_after_restore(local):
    first = _pin_old_forecast(local)
    _assert_forecast_snapshot(first, "20260912000000")
    assert "FORECAST_UPDATE_AVAILABLE" in {issue["code"] for issue in first["outcome"]["issues"]}
    assert local.app.forecast_refresh_requested(local.session, local.session.project)

    refreshed = json.loads(local.dispatch("calculate"))
    _assert_forecast_snapshot(refreshed, "20260912030000")
    assert "FORECAST_UPDATE_AVAILABLE" not in {
        issue["code"] for issue in refreshed["outcome"]["issues"]
    }
    assert local.app.forecast_refresh_requested(local.session, local.session.project)

    # Recovery never calculates. The next explicit unchanged action may refresh.
    restored = json.loads(local.dispatch("bootstrap", first["workingRecovery"]))
    _assert_forecast_snapshot(restored, "20260912000000")
    assert local.app.forecast_refresh_requested(local.session, local.session.project)
    _assert_forecast_snapshot(json.loads(local.dispatch("calculate")), "20260912030000")


@pytest.mark.parametrize("edit_back", [False, True])
def test_forecast_change_compares_with_last_success_including_edit_back(local, edit_back):
    _pin_old_forecast(local)
    original = local.session.project.sections[0].planned_altitude_ft_msl
    section = local.session.project.sections[0]
    for altitude in ([6000, original] if edit_back else [6000]):
        local.dispatch("updateProject", {
            "flight_date": "2026-09-12",
            "departure_time_jst": "12:00",
            "weather_mode": "FORECAST",
            "ftd_weather": local.session.project.ftd_weather.model_dump(mode="json"),
            "total_usable_fuel_gal": 90,
            "default_variation_deg_east": local.session.project.default_variation_deg_east,
            "sections": [{
                "section_id": str(section.id),
                "phase": section.phase.value,
                "planned_altitude_ft_msl": altitude,
            }],
        })
    assert local.app.forecast_refresh_requested(local.session, local.session.project) is edit_back
    state = json.loads(local.dispatch("calculate"))
    assert state["outcome"]["selected_forecast_run_id"] == (
        "20260912030000" if edit_back else "20260912000000"
    )
    assert local.app.forecast_refresh_requested(local.session, local.session.project)
    state = json.loads(local.dispatch("calculate"))
    assert state["outcome"]["selected_forecast_run_id"] == "20260912030000"


@pytest.mark.parametrize("failure", ["coverage", "acquisition", "processing"])
def test_forecast_refresh_failure_retains_last_good_and_never_reports_success(
    local, monkeypatch, failure
):
    first = _pin_old_forecast(local)
    last = first["workingRecovery"]["last_calculation"]
    provider = local.session.weather_provider
    if failure == "processing":
        target = "query_batch"
    elif failure == "coverage":
        target = "resolve_run"
    else:
        target = "prepare_run"

    def fail(*args, **kwargs):
        raise ValueError(f"refresh {failure} failed")

    with monkeypatch.context() as patch:
        patch.setattr(provider, target, fail)
        failed = json.loads(local.dispatch("calculate"))
    assert any(issue["severity"] == "BLOCKER" for issue in failed["readiness"]["issues"])
    assert any(issue["severity"] == "BLOCKER"
               for issue in failed["workingRecovery"]["outcome"]["issues"])
    assert failed["outcome"]["issues"] == failed["workingRecovery"]["outcome"]["issues"]
    assert failed["outcome"]["sections"] == first["outcome"]["sections"]
    assert failed["destinationWind"] == first["destinationWind"]
    assert first["verticalProfile"] is not None
    assert failed["verticalProfile"] == first["verticalProfile"]
    assert failed["verticalProfileStale"] is True
    assert failed["workingRecovery"]["last_calculation"] == last
    assert local.app.forecast_refresh_requested(local.session, local.session.project)


def test_ftd_never_requests_forecast_refresh(local):
    baseline = calculate(local)
    recalculated = json.loads(local.dispatch("calculate"))
    assert recalculated["outcome"]["summary"] == baseline["outcome"]["summary"]
    assert not local.app.forecast_refresh_requested(local.session, local.session.project)


@pytest.mark.parametrize("save_between_clicks", [False, True])
def test_portable_forecast_refresh_acquires_new_run_before_shared_calculation(save_between_clicks):
    from datetime import UTC, datetime, timedelta

    from scripts.local_reference import reference_state

    feed = ROOT / "tests/fixtures/msm-portable"
    initial = reference_state(feed=str(feed), pinned=True)
    catalog = json.loads((feed / "catalog.json").read_text())
    now = datetime.now(UTC)
    catalog.update(generated_at=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat())
    local = LocalApplication(ROOT / "data")
    try:
        local.dispatch("bootstrap", initial["workingRecovery"])
        for expected in ("20260915210000", "20260915210000"):
            result = _portable_calculation(local, feed, catalog)
            _assert_forecast_snapshot(result, expected)
            if save_between_clicks:
                # JSON.stringify represents integral JS Numbers without a decimal.
                def js_numbers(value):
                    if isinstance(value, dict):
                        return {key: js_numbers(item) for key, item in value.items()}
                    if isinstance(value, list):
                        return [js_numbers(item) for item in value]
                    if isinstance(value, float) and value.is_integer():
                        return int(value)
                    return value

                recovery = js_numbers(result["workingRecovery"])
                recovery["project"]["name"] = "Forecast refresh"
                recovery["project"]["revision"] += 1
                local.dispatch(
                    "adoptSavedProject",
                    {"working": recovery, "rounding_mode": result["roundingMode"]},
                )
                assert local.app.forecast_refresh_requested(local.session, local.session.project)
        assert "FORECAST_UPDATE_AVAILABLE" not in {
            issue["code"] for issue in result["outcome"]["issues"]
        }
    finally:
        local.close()


def test_forecast_refresh_persisted_repository_matches_snapshot(local):
    _pin_old_forecast(local)
    local.session.persist_working = True
    local.session.project.metadata["web_owner_id"] = local.session.owner_id
    refreshed = local.app.calculate(local.session)
    last = _assert_forecast_snapshot(refreshed, "20260912030000")
    service = local.app.project_service
    saved_project = service.load(local.session.project.id)
    saved_last = service.load_last_calculation(
        local.session.project.id, local.session.owner_id
    )
    assert saved_project.selected_forecast_run_id == "20260912030000"
    assert saved_last.selected_forecast_run_id == "20260912030000"
    assert saved_last.project.selected_forecast_run_id == "20260912030000"
    assert saved_last.outcome.selected_forecast_run_id == "20260912030000"
    assert saved_last.forecast_metadata == last["forecast_metadata"]
    assert saved_last.calculation_fingerprint == last["calculation_fingerprint"]


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("rounding_mode", [False, True])
def test_explicit_save_adoption_preserves_only_unchanged_forecast_intent(
    local, changed, rounding_mode
):
    first = _pin_old_forecast(local)
    if not rounding_mode:
        first = json.loads(local.dispatch("calculate", {"rounding_mode": False}))
    recovery = first["workingRecovery"]
    recovery["project"]["name"] = "Saved forecast"
    recovery["project"]["revision"] += 1
    if changed:
        recovery["project"]["sections"][0]["planned_altitude_ft_msl"] = 6000
    local.dispatch("adoptSavedProject", {"working": recovery, "rounding_mode": rounding_mode})
    assert local.session.rounding_mode is rounding_mode
    assert local.app.forecast_refresh_requested(
        local.session, local.session.project
    ) is (not changed)
    result = json.loads(local.dispatch("calculate"))
    assert result["outcome"]["selected_forecast_run_id"] == (
        "20260912000000" if changed else "20260912030000"
    )


@pytest.mark.parametrize("invalid_plan", [
    {"visual_reporting_point_node_id": "not-a-uuid"},
    "not-a-plan",
    {"visual_reporting_point_node_id": object()},
    {"visual_reporting_point_node_id": float("nan")},
])
def test_invalid_planning_cannot_request_refresh_and_preserves_state_error(
    local, invalid_plan,
):
    _pin_old_forecast(local)
    assert local.app.forecast_refresh_requested(local.session, local.session.project)
    local.session.project.metadata["ui_state"]["arrival_plan"] = invalid_plan
    with pytest.raises(ValueError, match="PROJECT_STATE_INVALID"):
        local.app.present(local.session)
    assert not local.app.forecast_refresh_requested(local.session, local.session.project)
    assert local.session.project.metadata["ui_state"]["arrival_plan"] is invalid_plan


@pytest.mark.parametrize("first_mode", [False, True])
def test_forecast_rounding_change_keeps_run_then_unchanged_action_refreshes(local, first_mode):
    _pin_old_forecast(local)
    if not first_mode:
        local.dispatch("calculate", {"rounding_mode": False})
    switched = json.loads(local.dispatch("calculate", {"rounding_mode": not first_mode}))
    _assert_forecast_snapshot(switched, "20260912000000")
    assert "FORECAST_UPDATE_AVAILABLE" in {issue["code"] for issue in switched["outcome"]["issues"]}
    refreshed = json.loads(local.dispatch("calculate", {"rounding_mode": not first_mode}))
    _assert_forecast_snapshot(refreshed, "20260912030000")


def test_portable_rounding_change_preflight_and_calculation_keep_the_same_pin():
    from datetime import UTC, datetime, timedelta

    from scripts.local_reference import reference_state

    feed = ROOT / "tests/fixtures/msm-portable"
    initial = reference_state(feed=str(feed), pinned=True)
    catalog = json.loads((feed / "catalog.json").read_text())
    now = datetime.now(UTC)
    catalog.update(generated_at=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat())
    local = LocalApplication(ROOT / "data")
    try:
        local.dispatch("bootstrap", initial["workingRecovery"])
        for mode, expected in [
            (False, "20260915180000"), (False, "20260915210000"),
        ]:
            options = {"rounding_mode": mode}
            state = _portable_calculation(local, feed, catalog, options)
            _assert_forecast_snapshot(state, expected)
            assert state["roundingMode"] is mode
    finally:
        local.close()


@pytest.mark.parametrize("forecast", [False, True])
@pytest.mark.parametrize("changed_input", [False, True])
def test_schema4_recovery_keeps_verified_fingerprint_and_does_not_promote_edits(
    local, forecast, changed_input,
):
    first = calculate(local, forecast=forecast)
    recovery = first["workingRecovery"]
    last = recovery["last_calculation"]
    fingerprint = last["calculation_fingerprint"]
    for project in [recovery["project"], last["project"]]:
        project["schema_version"] = 4
        project.pop("selected_forecast_model", None)
    for outcome in [recovery["outcome"], last["outcome"]]:
        outcome.pop("selected_forecast_model", None)
    last.pop("selected_forecast_model", None)
    if changed_input:
        recovery["project"]["tgl_count"] += 1
    restored = json.loads(local.dispatch("bootstrap", recovery))
    assert restored["readiness"]["calculationIsCurrent"] is (not changed_input)
    assert restored["workingRecovery"]["last_calculation"]["calculation_fingerprint"] == fingerprint
    restored_last = restored["workingRecovery"]["last_calculation"]
    assert restored_last["outcome"]["sections"] == last["outcome"]["sections"]


@pytest.mark.parametrize("old_value", [999, None])
def test_cut_restore_updates_only_derived_seconds_without_calculation(
    local, monkeypatch, old_value,
):
    calculated = calculate(local)
    recovery = json.loads(json.dumps(calculated["workingRecovery"]))
    for outcome in [recovery["outcome"], recovery["last_calculation"]["outcome"]]:
        for row in outcome["display_rows"]:
            if old_value is None:
                row.pop("thirty_degree_cut_seconds", None)
            else:
                row["thirty_degree_cut_seconds"] = old_value
    replacement = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    try:
        def forbidden(*args, **kwargs):
            raise AssertionError("CUT restoration must not recalculate or fetch weather")

        monkeypatch.setattr(replacement.session.calculation_service, "calculate", forbidden)
        restored = json.loads(replacement.dispatch("bootstrap", recovery))
        assert restored["workingRecovery"] == calculated["workingRecovery"]
        assert restored["outcome"] == calculated["outcome"]
        # A second save/reload retains only the new definition and all planning data.
        again = json.loads(replacement.dispatch("bootstrap", restored["workingRecovery"]))
        assert again["workingRecovery"] == restored["workingRecovery"]
    finally:
        replacement.close()
