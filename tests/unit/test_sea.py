from __future__ import annotations

from copy import deepcopy

import pytest
from geographiclib.geodesic import Geodesic
from pydantic import ValidationError

from autonavlog.application.sea import (
    RADIUS_M,
    SeaRecord,
    SeaTerrain,
    SeaUpdate,
    apply_sea,
    automatic_sea,
    contains_point,
    prune_sea,
    sea_plan,
)
from autonavlog.domain.project import Project
from tests.unit.test_checkpoints import _cp, _project


def complete(maximum: float) -> SeaTerrain:
    return SeaTerrain(complete=True, maximum_m=maximum, required=10, valid=10)


def patch(project, **values):
    return SeaUpdate(
        project_id=project.id, geometry_key=sea_plan(project)["geometry_key"], **values
    )


@pytest.mark.parametrize(
    ("metres", "expected"),
    [(0, 1000), (30.48, 1100), (30.48001, 1200), (304.8, 2000), (-30.48, 900)],
)
def test_ceiling_exact_100_ft_and_no_kml(metres, expected):
    assert automatic_sea(SeaRecord(terrain=complete(metres))) == expected


def test_missing_invalid_and_partial_maxima_never_become_automatic():
    for terrain in [
        SeaTerrain(),
        complete(30).model_copy(update={"complete": False}),
        complete(10000).model_copy(update={"missing": 1}),
        complete(10000).model_copy(update={"valid": 9}),
        complete(10000).model_copy(update={"invalid": 1}),
    ]:
        assert automatic_sea(SeaRecord(terrain=terrain, kml_maximum_m=10000)) is None
    with pytest.raises(ValidationError):
        complete(float("nan"))


def test_three_nm_boundary_forward_end_cap_and_no_rear():
    coordinates = [[131, 32], [131.1, 32]]
    assert contains_point(coordinates, coordinates[0])
    line = Geodesic.WGS84.InverseLine(32, 131, 32, 131.1)
    mid = line.Position(line.s13 / 2)
    for delta, expected in [(0, True), (-0.01, True), (0.01, False)]:
        p = Geodesic.WGS84.Direct(mid["lat2"], mid["lon2"], mid["azi2"] - 90, RADIUS_M + delta)
        assert contains_point(coordinates, [p["lon2"], p["lat2"]]) is expected
    end = line.Position(line.s13)
    p = Geodesic.WGS84.Direct(end["lat2"], end["lon2"], end["azi2"], RADIUS_M)
    assert contains_point(coordinates, [p["lon2"], p["lat2"]])
    rear = Geodesic.WGS84.Direct(32, 131, line.azi1 + 180, 0.01)
    assert not contains_point(coordinates, [rear["lon2"], rear["lat2"]])


def test_checkpoint_intervals_are_independent_and_manual_survives_non_geometry_edits():
    project = _project(_cp(latitude=0.02, longitude=0.4))
    plan = sea_plan(project, regions=True)
    a, b = plan["intervals"]
    assert a["to_name"] == b["from_name"] == "CP"
    assert a["key"] != b["key"]
    assert a["regions"] and b["regions"]
    apply_sea(
        project,
        patch(
            project,
            terrain={a["key"]: complete(30.48), b["key"]: complete(304.8)},
            manual={a["key"]: 1000, b["key"]: 3000},
        ),
    )
    values = sea_plan(project)["intervals"]
    assert [item["automatic_ft"] for item in values] == [1100, 2000]
    assert [item["warning"] for item in values] == ["below-automatic", None]
    project.sections[0].planned_altitude_ft_msl = 7000
    project.sections[0] = project.sections[0].model_copy(
        update={"manual_wind_direction_deg": 270, "manual_wind_speed_kt": 30}
    )
    project.route_nodes[0].name = "Renamed"
    project = Project.model_validate_json(project.model_dump_json())
    assert [item["manual_ft"] for item in sea_plan(project)["intervals"]] == [1000, 3000]
    project.visual_references[0].longitude_deg = 0.5
    prune_sea(project)
    assert all(item["manual_ft"] is None for item in sea_plan(project)["intervals"])
    # Returning to the old geometry must not resurrect an invalidated override.
    project.visual_references[0].longitude_deg = 0.4
    assert all(item["manual_ft"] is None for item in sea_plan(project)["intervals"])


def test_unknown_automatic_allows_manual_and_clearing_restores_warning():
    project = _project()
    key = sea_plan(project)["intervals"][0]["key"]
    apply_sea(project, patch(project, manual={key: 2500}))
    item = sea_plan(project)["intervals"][0]
    assert item["automatic_ft"] is None and item["status"] == "manual" and item["warning"] is None
    apply_sea(project, patch(project, manual={key: None}))
    assert sea_plan(project)["intervals"][0]["warning"] == "unconfirmed"


def test_kml_maximum_selection_datum_filter_and_does_not_fill_dem_holes():
    project = _project()
    key = sea_plan(project)["intervals"][0]["key"]
    kml = {
        "status": "available",
        "provenance": {
            "meaning": "terrain",
            "verticalReference": "TP",
            "source": "fixture",
            "demCompatibilityEvidence": "verified fixture",
        },
        "points": [
            {"coordinate": [0.5, 0], "elevationM": 304.8},
            {"coordinate": [-0.01, 0], "elevationM": 5000},
        ],
    }
    apply_sea(project, patch(project, terrain={key: complete(30.48)}, kml=kml))
    assert sea_plan(project)["intervals"][0]["automatic_ft"] == 2000
    apply_sea(project, patch(project, terrain={key: complete(609.6)}))
    assert sea_plan(project)["intervals"][0]["automatic_ft"] == 3000
    apply_sea(project, patch(project, terrain={key: SeaTerrain(maximum_m=10000)}))
    assert sea_plan(project)["intervals"][0]["automatic_ft"] is None
    kml["provenance"]["verticalReference"] = "EGM96"
    apply_sea(project, patch(project, terrain={key: complete(30.48)}, kml=kml))
    assert sea_plan(project)["intervals"][0]["automatic_ft"] == 1100


def test_stale_results_and_bad_optional_saved_data_do_not_corrupt_project():
    project = _project()
    update = patch(project)
    project.route_nodes[-1].longitude_deg += 0.1
    before = deepcopy(project)
    with pytest.raises(ValueError, match="stale"):
        apply_sea(project, update)
    assert project == before
    for raw in [
        None,
        [],
        {"policy": "sea-3nm-forward-cap-v1", "records": []},
        {"policy": "sea-3nm-forward-cap-v1", "records": {"bad": {"manual_ft": "oops"}}},
    ]:
        project.metadata["sea"] = raw
        assert sea_plan(project)["intervals"][0]["status"] == "unknown"


def test_repeated_geometry_does_not_transfer_manual_when_first_visit_is_removed():
    from uuid import uuid4

    project = _project()
    first = project.sections[0]
    second = first.model_copy(update={"id": uuid4(), "sequence": 1})
    project.sections.append(second)
    a, b = sea_plan(project)["intervals"]
    apply_sea(project, patch(project, manual={a["key"]: 3000, b["key"]: 5000}))
    project.sections = [second]
    prune_sea(project)
    remaining = sea_plan(project)["intervals"][0]
    assert remaining["key"] == b["key"]
    assert remaining["manual_ft"] == 5000


def test_dense_kml_maximum_stops_after_highest_accepted_point(monkeypatch):
    from autonavlog.application import sea

    project = _project()
    key = sea_plan(project)["intervals"][0]["key"]
    calls = []
    original = sea.contains_point

    def observed(coordinates, point):
        calls.append(point)
        return original(coordinates, point)

    monkeypatch.setattr(sea, "contains_point", observed)
    kml = {
        "status": "available",
        "provenance": {
            "meaning": "terrain",
            "verticalReference": "TP",
            "source": "fixture",
            "demCompatibilityEvidence": "same datum and epoch",
        },
        "points": [{"coordinate": [0.5, 0.01], "elevationM": i} for i in range(10000)],
    }
    apply_sea(project, patch(project, terrain={key: complete(30.48)}, kml=kml))
    assert len(calls) == 1
    assert sea_plan(project)["intervals"][0]["automatic_ft"] == 33900


def test_dense_outside_survey_is_rejected_before_precise_search(monkeypatch):
    from autonavlog.application import sea

    project = _project()
    for node in project.route_nodes:
        node.latitude_deg = 32
    project.route_nodes[0].longitude_deg = 131
    project.route_nodes[1].longitude_deg = 131.1
    key = sea_plan(project)["intervals"][0]["key"]
    calls = []
    original = sea.contains_point

    def observed(coordinates, point):
        calls.append(point)
        return original(coordinates, point)

    monkeypatch.setattr(sea, "contains_point", observed)
    kml = {
        "status": "available",
        "provenance": {
            "meaning": "terrain",
            "verticalReference": "TP",
            "source": "fixture",
            "demCompatibilityEvidence": "same datum and epoch",
        },
        "points": [{"coordinate": [131.05, 32.06], "elevationM": i} for i in range(10000)],
    }
    apply_sea(project, patch(project, terrain={key: complete(30.48)}, kml=kml))
    assert calls == []
    assert sea_plan(project)["intervals"][0]["automatic_ft"] == 1100
