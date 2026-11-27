"""Departure VOR changes the horizontal origin, never the airport performance inputs."""

import json
from pathlib import Path

import pytest

from autonavlog.domain.airport_vor import AIRPORT_VORS
from autonavlog.domain.planning import load_persisted_ui_state
from autonavlog.local import LocalApplication

ROOT = Path(__file__).resolve().parents[2]
INPUT = json.loads((ROOT / "tests/fixtures/issue_117_ftd.json").read_text())


def route(airport, mode="VOR"):
    destination = "RJFO" if airport != "RJFO" else "RJFM"
    return {
        **INPUT["confirm"],
        "candidate_kind": "map",
        "departure_origin": mode,
        "map_points": [
            {"name": airport, "airport_id": airport, "latitude_deg": 32.0, "longitude_deg": 131.0},
            {"name": "CP", "latitude_deg": 32.5, "longitude_deg": 131.5},
            {
                "name": destination,
                "airport_id": destination,
                "latitude_deg": 33.0,
                "longitude_deg": 131.0,
            },
        ],
    }


def update(project, mode=None):
    result = {
        key: INPUT["confirm"][key]
        for key in (
            "flight_date",
            "departure_time_jst",
            "weather_mode",
            "ftd_weather",
            "default_variation_deg_east",
        )
    }
    result["total_usable_fuel_gal"] = 90
    if mode is not None:
        result["departure_origin"] = mode
    return result


@pytest.mark.parametrize("airport", AIRPORT_VORS)
def test_all_airport_origins_and_roundtrip(airport):
    app = LocalApplication(ROOT / "data")
    try:
        base = json.loads(app.dispatch("confirmRoute", route(airport, "AIRPORT")))
        original = base["project"]
        state = json.loads(app.dispatch("updateProject", update(original, "VOR")))
        project = state["project"]
        vor = AIRPORT_VORS[airport]
        first = project["route_nodes"][0]
        assert first["name"] == vor.identifier
        assert first["latitude_deg"] == vor.latitude_deg
        assert first["longitude_deg"] == vor.longitude_deg
        assert project["route_nodes"][-1] == original["route_nodes"][-1]
        assert project["departure_airport_id"] == airport
        assert (
            project["metadata"]["ui_state"]["reference_data_snapshot"]
            == original["metadata"]["ui_state"]["reference_data_snapshot"]
        )
        assert project["metadata"]["ui_state"]["departure_vor"] == vor.model_dump(mode="json")
        restored = json.loads(app.dispatch("bootstrap", state["workingRecovery"]))
        assert restored["project"]["route_nodes"][0] == first
        unchanged = json.loads(app.dispatch("updateProject", update(restored["project"])))
        assert unchanged["project"]["route_nodes"][0] == first
        returned = json.loads(app.dispatch("updateProject", update(project, "AIRPORT")))
        assert (
            returned["project"]["route_nodes"][0]["latitude_deg"]
            == original["route_nodes"][0]["latitude_deg"]
        )
        assert returned["project"]["metadata"]["ui_state"]["departure_vor"] is None
    finally:
        app.close()


@pytest.mark.parametrize("kind", ["map", "line"])
def test_initial_vor_selection_and_calculation(kind):
    app = LocalApplication(ROOT / "data")
    try:
        if kind == "map":
            request = route("RJOB")  # OYE is off-airport and >0.5 NM from the ARP.
        else:
            app.dispatch(
                "importRoute",
                {
                    "filename": "route.kml",
                    "kml_text": (ROOT / "tests/fixtures/issue_43_golden.kml").read_text(),
                },
            )
            request = {**INPUT["confirm"], "departure_origin": "VOR"}
        state = json.loads(app.dispatch("confirmRoute", request))
        project = state["project"]
        assert project["metadata"]["ui_state"]["departure_vor"] is not None
        result = json.loads(app.dispatch("calculate"))
        assert "ROUTE_AIRPORT_ENDPOINT_MISMATCH" not in {
            issue["code"] for issue in result["outcome"]["issues"]
        }
        assert result["outcome"]["sections"]
        # Switching after a result must require recalculation.
        changed = json.loads(app.dispatch("updateProject", update(project, "AIRPORT")))
        assert not changed["readiness"]["calculationIsCurrent"]
    finally:
        app.close()


def test_schema7_loads_as_airport_and_rejects_new_field():
    old = {"state_schema_version": 7}
    state = load_persisted_ui_state(old)
    assert state.state_schema_version == 8
    assert state.departure_vor is None
    with pytest.raises(ValueError):
        load_persisted_ui_state(
            {**old, "departure_vor": AIRPORT_VORS["RJFM"].model_dump(mode="json")}
        )


def test_vor_mapping_covers_the_registered_airports_and_matches_evidence():
    from autonavlog.storage.reference_data import ReferenceDataCatalogRepository

    catalog = ReferenceDataCatalogRepository(ROOT / "data/reference").open_pack(
        ROOT / "data/reference/default"
    )
    assert set(AIRPORT_VORS) == set(catalog.airports)
    evidence = json.loads((ROOT / "docs/evidence/airport-vor-departure.json").read_text())
    for station in evidence["stations"]:
        adopted = AIRPORT_VORS[station["airport_id"]]
        assert adopted.identifier == station["vor_identifier"]
        assert adopted.latitude_deg == station["latitude_deg"]
        assert adopted.longitude_deg == station["longitude_deg"]
        assert adopted.source_revision == station["source_sha256"]


@pytest.mark.parametrize("initial_mode", ["AIRPORT", "VOR"])
def test_mode_roundtrip_cannot_revalidate_an_old_calculation(initial_mode):
    app = LocalApplication(ROOT / "data")
    try:
        app.dispatch(
            "importRoute",
            {
                "filename": "route.kml",
                "kml_text": (ROOT / "tests/fixtures/issue_43_golden.kml").read_text(),
            },
        )
        app.dispatch("confirmRoute", {**INPUT["confirm"], "departure_origin": initial_mode})
        calculated = json.loads(app.dispatch("calculate"))
        assert calculated["readiness"]["calculationIsCurrent"]
        project = calculated["project"]
        other_mode = "VOR" if initial_mode == "AIRPORT" else "AIRPORT"
        changed = json.loads(app.dispatch("updateProject", update(project, other_mode)))
        assert not changed["readiness"]["calculationIsCurrent"]
        returned = json.loads(app.dispatch("updateProject", update(project, initial_mode)))
        assert not returned["readiness"]["calculationIsCurrent"]
        assert returned["project"]["metadata"]["ui_state"]["calculated_against_fingerprint"] is None
        restored = json.loads(app.dispatch("bootstrap", returned["workingRecovery"]))
        assert not restored["readiness"]["calculationIsCurrent"]
        refreshed = json.loads(app.dispatch("calculate"))
        assert refreshed["readiness"]["calculationIsCurrent"]
        unchanged = json.loads(app.dispatch("updateProject", update(project, initial_mode)))
        assert unchanged["readiness"]["calculationIsCurrent"]
    finally:
        app.close()


def ole_request(course=87.0):
    from autonavlog.nav.geodesy import point_along_leg

    request = route("RJFU")
    vor = AIRPORT_VORS["RJFU"]
    lat, lon = point_along_leg(vor.latitude_deg, vor.longitude_deg, course, 50)
    request["map_points"][1].update(latitude_deg=lat, longitude_deg=lon)
    return request


def value(zone, key):
    field = zone[key]
    return (field["manual_override"] if field["adopted_source"] == "MANUAL"
            else field["automatic_value"])


@pytest.mark.parametrize("course,display_mc", [(87.0, 94), (87.499, 94), (87.501, 95)])
@pytest.mark.parametrize("rounding_mode", [False, True])
def test_ole_radial_split_zones_and_display_arithmetic(course, display_mc, rounding_mode):
    from autonavlog.domain.enums import VisualReferenceRole
    from autonavlog.domain.project import VisualReference
    from autonavlog.nav.geodesy import geodesic_leg, point_along_leg
    from autonavlog.nav.wind_triangle import solve_wind_triangle

    app = LocalApplication(ROOT / "data")
    try:
        app.dispatch("confirmRoute", ole_request(course))
        # The arbitrary VREP is far from RJFO: its distance-based arrival
        # altitude exceeds this fixture's 3,000 ft cruise. Use an explicit
        # arrival altitude to keep testing radial arithmetic across all zones.
        app.dispatch("updateProject", {
            **update(app.session.project),
            "arrival_altitude_mode": "MANUAL_NON_STANDARD_ENTRY",
            "manual_vrep_altitude_ft_msl": 2500,
            "manual_vrep_reason": "VOR radial arithmetic fixture",
        })
        project = app.session.project
        vor = AIRPORT_VORS["RJFU"]
        lat, lon = point_along_leg(vor.latitude_deg, vor.longitude_deg, course, 20)
        project.visual_references.append(VisualReference(
            name="ABEAM", latitude_deg=lat + 0.01, longitude_deg=lon,
            role=VisualReferenceRole.CHECK_POINT,
            linked_section_id=project.ordered_sections()[0].id,
        ))
        state = json.loads(app.dispatch("calculate", {"rounding_mode": rounding_mode}))
        outcome = state["outcome"]
        assert not any(issue["severity"] == "BLOCKER" for issue in outcome["issues"])
        first_id = str(project.ordered_sections()[0].id)
        zones = [z for z in outcome["sections"] if z["section_id"] == first_id]
        assert any(z["to_name"] == "RCA" for z in zones)
        assert any(z["to_name"] == "CP:ABEAM" for z in zones)
        assert len(zones) >= 3
        for zone in zones:
            assert value(zone, "true_course_deg") == pytest.approx(course - 1)
            assert value(zone, "variation_deg_east") == 8
            assert zone["variation_deg_east"]["automatic_metadata"]["method"] == (
                "LEG_DEPARTURE_LATITUDE_BAND"
            )
            assert zone["true_course_deg"]["automatic_metadata"][
                "vor_tracking_tc_correction_deg"
            ] == 1
            assert value(zone, "magnetic_course_deg") == pytest.approx(course + 7)
            radial = geodesic_leg(vor.latitude_deg, vor.longitude_deg,
                                  zone["to_latitude_deg"], zone["to_longitude_deg"])
            assert radial.initial_true_course_deg + 7 == pytest.approx(course + 7, abs=1e-7)
            wind = solve_wind_triangle(
                course, value(zone, "tas_kt"),
                value(zone, "wind_direction_deg_from"), value(zone, "wind_speed_kt"),
            )
            assert value(zone, "wca_deg") == pytest.approx(wind.wca_deg)
            assert value(zone, "magnetic_heading_deg") == pytest.approx(
                (course + 7 + wind.wca_deg) % 360
            )
        later = [z for z in outcome["sections"] if z["section_id"] != first_id]
        assert later
        assert all(value(z, "variation_deg_east") == 8 for z in later)
        rows = [r for r in outcome["display_rows"] if r["section_id"] == first_id]
        assert int(rows[0]["mc"]["text"]) == display_mc
        checked = 0
        for row in rows:
            if row["mh"]["text"] is not None:
                mc = int(row["mc"]["text"] or rows[0]["mc"]["text"])
                wca = int(row["wca"]["text"])
                assert int(row["mh"]["text"]) % 360 == (mc + wca) % 360
                checked += 1
        assert checked
        # Local bearings along the geodesic change, but the station radial stays fixed.
        tangent = geodesic_leg(zones[-1]["from_latitude_deg"], zones[-1]["from_longitude_deg"],
                               zones[-1]["to_latitude_deg"], zones[-1]["to_longitude_deg"])
        assert abs(tangent.initial_true_course_deg - course) > 0.01
    finally:
        app.close()



def test_vor_tc_correction_preserves_manual_route_input_and_physical_wind():
    from autonavlog.nav.wind_triangle import solve_wind_triangle

    app = LocalApplication(ROOT / "data")
    try:
        app.dispatch("confirmRoute", ole_request())
        origin = app.session.project.ordered_nodes()[0]
        origin.manual_true_course_deg = 87.5
        state = json.loads(app.dispatch("calculate"))
        zone = state["outcome"]["sections"][0]
        assert origin.manual_true_course_deg == 87.5
        assert value(zone, "true_course_deg") == pytest.approx(86.5)
        assert zone["true_course_deg"]["adopted_source"] == "MANUAL"
        assert value(zone, "variation_deg_east") == 8
        assert value(zone, "magnetic_course_deg") == pytest.approx(94.5)
        wind = solve_wind_triangle(
            87.5,
            value(zone, "tas_kt"),
            value(zone, "wind_direction_deg_from"),
            value(zone, "wind_speed_kt"),
        )
        assert value(zone, "wca_deg") == pytest.approx(wind.wca_deg)
    finally:
        app.close()

def test_first_leg_eoc_keeps_vor_reference():
    app = LocalApplication(ROOT / "data")
    try:
        request = ole_request()
        destination = app.app.airports.get("RJFO")
        request["map_points"][1].update(
            latitude_deg=destination.latitude_deg - 0.01,
            longitude_deg=destination.longitude_deg,
        )
        app.dispatch("confirmRoute", request)
        from autonavlog.domain.enums import FlightPhase

        app.session.project.sections[0].phase = FlightPhase.DESCENT
        app.session.project.sections[0].planned_altitude_ft_msl = 6000
        result = json.loads(app.dispatch("calculate"))["outcome"]
        first_id = str(app.session.project.ordered_sections()[0].id)
        zones = [z for z in result["sections"] if z["section_id"] == first_id]
        assert any(z["from_name"] == "EOC" for z in zones)
        assert all(value(z, "variation_deg_east") == 8 for z in zones)
        assert all(
            z["true_course_deg"]["automatic_metadata"]["vor_tracking_tc_correction_deg"] == 1
            for z in zones
        )
    finally:
        app.close()


@pytest.mark.parametrize("problem", ["missing", "unknown", "moved_station", "moved_origin"])
def test_unavailable_declination_never_falls_back_to_latitude(problem, monkeypatch):
    from autonavlog.nav.variation import VOR_DECLINATIONS

    app = LocalApplication(ROOT / "data")
    try:
        app.dispatch("confirmRoute", ole_request())
        project = app.session.project
        if problem == "missing":
            monkeypatch.delitem(VOR_DECLINATIONS, "OLE")
        elif problem == "unknown":
            project.metadata["ui_state"]["departure_vor"]["identifier"] = "UNKNOWN"
        elif problem == "moved_station":
            project.metadata["ui_state"]["departure_vor"]["latitude_deg"] += 0.001
        else:
            project.route_nodes[0].latitude_deg += 0.001  # Inside the old 0.5 NM tolerance.
        state = json.loads(app.dispatch("calculate"))
        assert any(i["code"] == "VARIATION_UNAVAILABLE" for i in state["outcome"]["issues"])
        first = state["outcome"]["sections"][0]
        assert value(first, "variation_deg_east") == 8
        assert value(first, "magnetic_course_deg") is None
        assert value(first, "magnetic_heading_deg") is None
        assert any(i["severity"] == "BLOCKER" for i in state["outcome"]["issues"])
    finally:
        app.close()


def test_tracking_uses_packaged_station_resource():
    from importlib.resources import files

    from autonavlog.nav.variation import variation_for_departure_vor

    # Works against installed wheels/Docker without the repository's Web sources.
    resource = files("autonavlog.nav").joinpath("data/vor_stations.json")
    data = json.loads(resource.read_text())
    visible = {s["identifier"] for s in data["stations"]}
    assert "OLE" in visible
    assert "OYE" not in visible
    stations = {s["identifier"]: s for s in
                (*data["stations"], *data["departure_only_stations"])}
    for vor in AIRPORT_VORS.values():
        station = stations[vor.identifier]
        decision = variation_for_departure_vor(vor)
        assert decision.degrees_east == station["variation_west_deg"]
        assert decision.metadata["source"] == (
            f"AIP {station['variation_source']}; "
            f"{station['source_file']} p.{station['source_page']}"
        )
    oye = variation_for_departure_vor(AIRPORT_VORS["RJOB"])
    assert oye.degrees_east == 8
    assert oye.metadata["source"] == (
        "AIP AD 2.19 VOR declination (8°W/2016); RJOB__AD2_20260806.pdf p.7"
    )


@pytest.mark.parametrize("mode", ["VOR", "AIRPORT"])
def test_pre_vor_rule_saved_calculation_requires_recalculation_only_in_vor_mode(mode, monkeypatch):
    import autonavlog.application.project_fingerprints as fingerprints

    app = LocalApplication(ROOT / "data")
    try:
        request = ole_request()
        request["departure_origin"] = mode
        app.dispatch("confirmRoute", request)
        original = fingerprints.make_fingerprint

        def old_fingerprint(*, kind, fields):
            fields = dict(fields)
            fields.pop("departure_vor_variation", None)
            return original(kind=kind, fields=fields)

        with monkeypatch.context() as old:
            old.setattr(fingerprints, "make_fingerprint", old_fingerprint)
            previous = json.loads(app.dispatch("calculate"))
            assert previous["readiness"]["calculationIsCurrent"]
        restored = json.loads(app.dispatch("bootstrap", previous["workingRecovery"]))
        assert restored["readiness"]["calculationIsCurrent"] == (mode == "AIRPORT")
        refreshed = json.loads(app.dispatch("calculate"))
        assert refreshed["readiness"]["calculationIsCurrent"]
        if mode == "VOR":
            first = refreshed["outcome"]["sections"][0]
            assert value(first, "magnetic_course_deg") == pytest.approx(94)
            from autonavlog.nav.variation import VOR_DECLINATIONS

            monkeypatch.setitem(VOR_DECLINATIONS, "OLE", (8.0, "changed reference"))
            changed = json.loads(app.dispatch("bootstrap", refreshed["workingRecovery"]))
            assert not changed["readiness"]["calculationIsCurrent"]
    finally:
        app.close()
