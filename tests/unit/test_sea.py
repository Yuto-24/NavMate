from __future__ import annotations

from copy import deepcopy

import pytest
from geographiclib.geodesic import Geodesic
from pydantic import ValidationError

from autonavlog.application.sea import (
    LEGACY_POLICY,
    POLICY,
    RADIUS_M,
    SeaRecord,
    SeaTerrain,
    SeaUpdate,
    apply_sea,
    automatic_sea,
    contains_point,
    legacy_interval_keys,
    prune_sea,
    sea_plan,
)
from autonavlog.domain.project import Project
from tests.unit.test_checkpoints import _cp, _project


def complete(maximum: float) -> SeaTerrain:
    return SeaTerrain(complete=True, maximum_m=maximum, required=10, valid=10)


def patch(project, **values):
    # Seed legacy storage directly; the retired API must no longer accept edits.
    manual = values.pop("manual", {})
    raw = project.metadata.setdefault("sea", {"policy": POLICY, "records": {}})
    for key, value in manual.items():
        raw["records"].setdefault(key, {})["manual_ft"] = value
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


def test_three_nm_boundary_with_both_normal_end_planes():
    coordinates = [[131, 32], [131.1, 32]]
    assert contains_point(coordinates, coordinates[0])
    line = Geodesic.WGS84.InverseLine(32, 131, 32, 131.1)
    mid = line.Position(line.s13 / 2)
    for delta, expected in [(0, True), (-0.01, True), (0.01, False)]:
        p = Geodesic.WGS84.Direct(mid["lat2"], mid["lon2"], mid["azi2"] - 90, RADIUS_M + delta)
        assert contains_point(coordinates, [p["lon2"], p["lat2"]]) is expected
    end = line.Position(line.s13)
    p = Geodesic.WGS84.Direct(end["lat2"], end["lon2"], end["azi2"], RADIUS_M)
    assert not contains_point(coordinates, [p["lon2"], p["lat2"]])
    for station in [line.Position(0), end]:
        p = Geodesic.WGS84.Direct(station["lat2"], station["lon2"], station["azi2"] - 90, RADIUS_M)
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
    assert [item["warning"] for item in values] == [None, None]
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


def test_legacy_manual_does_not_hide_unknown_automatic():
    project = _project()
    key = sea_plan(project)["intervals"][0]["key"]
    apply_sea(project, patch(project, manual={key: 2500}))
    item = sea_plan(project)["intervals"][0]
    assert item["automatic_ft"] is None
    assert item["status"] == "unknown" and item["warning"] == "unconfirmed"
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


@pytest.mark.parametrize(
    "coordinates",
    [
        [[131, 51], [131.1, 51]],
        [[131, -51], [131.1, -51]],
        [[131, 32], [140, 32]],
        [[179.9, 32], [-179.9, 32]],
        [[131, 32], [131, 32]],
    ],
)
def test_unsupported_automatic_input_and_saved_records_preserve_manual(coordinates):
    project = _project()
    for node, (lon, lat) in zip(project.route_nodes, coordinates, strict=True):
        node.longitude_deg, node.latitude_deg = lon, lat
    interval = sea_plan(project, regions=True)["intervals"][0]
    assert interval["regions"] == []
    key = interval["key"]
    apply_sea(project, patch(project, terrain={key: complete(304.8)}, manual={key: 2500}))
    # The same policy applies to posted evidence and a round trip through storage.
    for saved in (project, Project.model_validate_json(project.model_dump_json())):
        value = sea_plan(saved)["intervals"][0]
        assert value["automatic_ft"] is None
        assert value["manual_ft"] == 2500
        assert value["value_ft"] is None
        assert value["status"] == "unknown" and value["warning"] == "unconfirmed"
    apply_sea(project, patch(project, manual={key: None}))
    value = sea_plan(project)["intervals"][0]
    assert value["automatic_ft"] is None and value["value_ft"] is None
    assert value["status"] == "unknown" and value["warning"] == "unconfirmed"


def test_retired_manual_update_is_rejected_without_mutation():
    project = _project()
    plan = sea_plan(project)
    before = project.model_dump()
    with pytest.raises(ValueError, match="manual-sea-retired"):
        apply_sea(project, SeaUpdate(project_id=project.id, geometry_key=plan["geometry_key"],
                                    manual={plan["intervals"][0]["key"]: 2000}))
    assert project.model_dump() == before


@pytest.mark.parametrize("maximum, expected", [(0, 1000), (-30.48, 900), (304.8, 2000)])
def test_fully_evaluated_missing_dem_is_reference(maximum, expected):
    project = _project()
    key = sea_plan(project)["intervals"][0]["key"]
    terrain = SeaTerrain(evaluated=True, maximum_m=maximum, required=10, valid=6, missing=4)
    apply_sea(project, patch(project, terrain={key: terrain}))
    restored = Project.model_validate_json(project.model_dump_json())
    for saved in (project, restored):
        value = sea_plan(saved)["intervals"][0]
        assert value["automatic_ft"] == expected
        assert value["value_ft"] == expected
        assert value["reference"] is True
        assert value["terrain"]["evaluated"] is True
    assert automatic_sea(SeaRecord(terrain=terrain, kml_maximum_m=609.6)) == 3000
    apply_sea(project, patch(project, terrain={key: complete(30.48)}))
    value = sea_plan(project)["intervals"][0]
    assert value["automatic_ft"] == 1100
    assert value["reference"] is False


@pytest.mark.parametrize("changes", [
    {"evaluated": False},
    {"valid": 0, "missing": 10, "maximum_m": None},
    {"valid": 5, "not_acquired": 1},
    {"valid": 5, "invalid": 1},
    {"required": 11},
])
def test_reference_rejects_old_partial_missing_only_and_failures(changes):
    terrain = SeaTerrain(evaluated=True, maximum_m=304.8, required=10, valid=6, missing=4)
    assert automatic_sea(SeaRecord(
        terrain=terrain.model_copy(update=changes), kml_maximum_m=10000
    )) is None


def _turn_project(latitude):
    from uuid import uuid4

    project = _project()
    project.route_nodes[0].longitude_deg = -0.1
    project.route_nodes[1].longitude_deg = 0
    end = project.route_nodes[1].model_copy(update={
        "id": uuid4(), "name": "C", "sequence": 2, "latitude_deg": latitude,
    })
    project.route_nodes.append(end)
    project.sections.append(project.sections[0].model_copy(update={
        "id": uuid4(), "sequence": 1, "from_node_id": project.route_nodes[1].id,
        "to_node_id": end.id,
    }))
    return project


@pytest.mark.parametrize("latitude,bearing,angle", [(-0.1, 45, 90), (0.1, 135, -90)])
def test_outer_turn_sector_shared_by_both_intervals_and_kml_maximum(latitude, bearing, angle):
    from autonavlog.application.sea import _sector_contains

    project = _turn_project(latitude)
    a, b = sea_plan(project, regions=True)["intervals"]
    assert a["turns"] == b["turns"]
    assert a["turns"][0]["angle"] == pytest.approx(angle)
    assert a["regions"][-1] == b["regions"][-1]
    point = Geodesic.WGS84.Direct(0, 0, bearing, RADIUS_M)
    coordinate = [point["lon2"], point["lat2"]]
    assert not contains_point(a["coordinates"], coordinate)
    assert not contains_point(b["coordinates"], coordinate)
    assert _sector_contains(a["turns"][0], coordinate)
    beyond = Geodesic.WGS84.Direct(0, 0, bearing, RADIUS_M + 0.01)
    assert not _sector_contains(a["turns"][0], [beyond["lon2"], beyond["lat2"]])
    apply_sea(project, patch(project, terrain={item["key"]: complete(30.48) for item in [a, b]},
        kml={"status": "available", "provenance": {
            "meaning": "terrain", "verticalReference": "TP", "source": "fixture",
            "demCompatibilityEvidence": "same datum and epoch",
        }, "points": [{"coordinate": coordinate, "elevationM": 304.8}]}))
    assert [item["automatic_ft"] for item in sea_plan(project)["intervals"]] == [2000, 2000]


def test_straight_physical_boundary_has_no_sector_or_longitudinal_extension():
    project = _turn_project(0)
    project.route_nodes[-1].longitude_deg = 0.1
    plan = sea_plan(project, regions=True)
    assert all(not item["turns"] for item in plan["intervals"])
    for item in plan["intervals"]:
        vertices = [p for region in item["regions"] for p in region]
        assert min(p[0] for p in vertices) >= item["coordinates"][0][0] - 1e-10
        assert max(p[0] for p in vertices) <= item["coordinates"][1][0] + 1e-10


@pytest.mark.parametrize("bearing", [0, 45, 90, 135, 180])
def test_grid_aligned_endpoint_and_cp_do_not_create_degenerate_raster_regions(bearing):
    from autonavlog.application.sea import _regions

    def point(distance):
        p = Geodesic.WGS84.Direct(32, 131, bearing, distance)
        return [p["lon2"], p["lat2"]]

    end, cp = point(18520), point(9260)
    leg = [[131, 32], end]
    for coordinates, expected in [(leg, 10), ([[131, 32], cp], 5), ([cp, end], 5)]:
        regions = _regions(coordinates, leg)
        assert len(regions) == expected
        assert all(len({tuple(v) for v in region}) == 4 for region in regions)
    # A real 1 mm offset remains an exact boundary, not rounded to the 5 NM grid.
    shifted = point(9260.001)
    assert len(_regions([[131, 32], shifted], leg)) == 6
    assert _regions([[131, 32], shifted], leg)[-1] != _regions([[131, 32], cp], leg)[-1]


def test_cp_forward_terrain_is_excluded_and_common_strips_survive_cp_edits():
    import json

    project = _project(_cp(latitude=0.02, longitude=0.4), _cp(latitude=0.02, longitude=0.40002))
    plan = sea_plan(project, regions=True)
    assert len(plan["intervals"]) == 3  # Includes a two-metre CP interval.
    a, tiny, b = plan["intervals"]
    assert all(item["regions"] for item in [a, tiny, b])
    point = [0.40003, 0]
    assert not contains_point(a["coordinates"], point)
    assert not contains_point(tiny["coordinates"], point)
    assert contains_point(b["coordinates"], point)
    def polygons(p):
        return {json.dumps(r) for i in p["intervals"] for r in i["regions"]}
    original = polygons(plan)
    project.visual_references = project.visual_references[:1]
    project.visual_references[0].longitude_deg = 0.41
    moved = polygons(sea_plan(project, regions=True))
    assert len(original - moved) <= 5
    assert len(moved - original) <= 3
    project.visual_references = []
    removed = polygons(sea_plan(project, regions=True))
    assert len(moved - removed) == 2
    assert len(removed - moved) == 1


def test_turn_change_invalidates_adjacent_cp_interval_but_not_distant_common_interval():
    project = _turn_project(-0.1)
    cp = _cp(latitude=0.01, longitude=-0.05).model_copy(update={
        "linked_section_id": project.sections[0].id,
    })
    project.visual_references = [cp]
    before = sea_plan(project, regions=True)["intervals"]
    project.route_nodes[-1].longitude_deg = 0.05
    after = sea_plan(project, regions=True)["intervals"]
    assert before[0]["key"] == after[0]["key"]
    assert before[0]["regions"] == after[0]["regions"]
    assert before[1]["key"] != after[1]["key"]
    assert before[1]["regions"][:-1] == after[1]["regions"][:-1]
    assert before[2]["key"] != after[2]["key"]


def test_old_policy_re_evaluates_preserving_manual_kml_and_diagnostics():
    project = _project()
    old_key, new_key = next(iter(legacy_interval_keys(project).items()))
    old = {"policy": LEGACY_POLICY, "records": {
        old_key: SeaRecord(terrain=complete(304.8), manual_ft=5000).model_dump(mode="json")
    }, "kml": {"status": "unconfirmed", "points": []}}
    project.metadata["sea"] = deepcopy(old)
    prune_sea(project)
    item = sea_plan(project)["intervals"][0]
    assert item["automatic_ft"] is None and item["manual_ft"] == 5000
    assert project.metadata["sea"] == old
    apply_sea(project, patch(project, terrain={new_key: complete(30.48)}))
    assert project.metadata["sea"]["legacy"] == old
    assert project.metadata["sea"]["kml"] == old["kml"]
    item = sea_plan(Project.model_validate_json(project.model_dump_json()))["intervals"][0]
    assert item["automatic_ft"] == 1100 and item["manual_ft"] == 5000
