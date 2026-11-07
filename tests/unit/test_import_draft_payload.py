"""Draft candidates retain source geometry separately from bounded map previews."""

import pytest

from autonavlog.importers.kml import (
    ImportedConnectedLine,
    ImportedLine,
    ImportedPoint,
    ImportedPolygon,
    KmlImportResult,
    import_kml_text,
)
from autonavlog.web.facade import AutoNavLogWebApplication


@pytest.mark.parametrize("count", [4, 500, 501, 2100])
@pytest.mark.parametrize("kind", ["line", "connected_lines", "polygon", "points"])
def test_candidate_payload_keeps_original_coordinates_within_map_limit(kind, count):
    coordinates = tuple((32 + i * 0.001, 131.0) for i in range(count))
    preview = (coordinates[0], coordinates[-1])
    if kind == "line":
        result = KmlImportResult(lines=(ImportedLine("line", coordinates, preview),))
    elif kind == "connected_lines":
        result = KmlImportResult(connected_lines=(ImportedConnectedLine(
            name="joined", container_path=(), segment_names=("a", "b"),
            segment_indices=(0, 1), coordinates=coordinates,
            waypoint_names=(None,) * count, waypoint_sources=(None,) * count,
            distance_nm=1, max_join_gap_nm=0, display_coordinates=preview,
        ),))
    elif kind == "polygon":
        coordinates = (*coordinates[:-1], coordinates[0])
        result = KmlImportResult(polygons=(ImportedPolygon(
            "polygon", coordinates, display_outer_boundary=preview,
        ),))
    else:
        result = KmlImportResult(points=tuple(
            ImportedPoint(str(i), lat, lon) for i, (lat, lon) in enumerate(coordinates)
        ))
    facade = object.__new__(AutoNavLogWebApplication)
    facade._nearest_airport_within_5_nm = lambda _: None
    candidate = AutoNavLogWebApplication._candidate_payload(facade, result)["candidates"][0]
    assert candidate["vertexCount"] == count
    assert candidate["routeCoordinates"] == (
        [list(item) for item in coordinates] if count <= 500 else None
    )
    if kind == "line":
        assert candidate["coordinates"] == [list(item) for item in preview]
        assert len(candidate["coordinates"]) < count


def candidates(text):
    facade = object.__new__(AutoNavLogWebApplication)
    facade._nearest_airport_within_5_nm = lambda _: None
    return facade._candidate_payload(import_kml_text(text))["candidates"]


def placemark(name, kind, coordinates):
    label = f"<name>{name}</name>" if name is not None else ""
    return (f"<Placemark>{label}<{kind}><coordinates>{coordinates}</coordinates>"
            f"</{kind}></Placemark>")


def test_point_names_distinguish_missing_empty_and_literal_unnamed():
    text = "<kml><Document>" + "".join(
        placemark(name, "Point", f"131,{31 + index}")
        for index, name in enumerate(["START", "山", None, " ", "Unnamed", "END"])
    ) + "</Document></kml>"
    candidate = candidates(text)[0]
    assert candidate["routeNames"] == ["START", "山", None, None, "Unnamed", "END"]
    assert candidate["vertexCount"] == len(candidate["routeNames"])


@pytest.mark.parametrize(("name", "expected"), [
    ("START→ONE→TWO→END", ["START", "ONE", "TWO", "END"]),
    ("ONE→TWO", [None, "ONE", "TWO", None]),
    ("ONE→TWO→THREE", [None] * 4),
    ("route title", [None] * 4),
    (None, [None] * 4),
])
def test_line_name_slots_do_not_guess_ambiguous_titles(name, expected):
    line = placemark(name, "LineString", "131,31 131,32 131,33 131,34")
    candidate = candidates(f"<kml><Document>{line}</Document></kml>")[0]
    assert candidate["routeNames"] == expected
    assert candidate["routeCoordinates"] == [[31, 131], [32, 131], [33, 131], [34, 131]]


@pytest.mark.parametrize("folder_name", ["B", "A", None])
def test_line_point_fallback_is_scoped_to_its_container(folder_name):
    line = placemark("route", "LineString", "131,31 131,32 131,33 131,34")
    own = placemark("OWN", "Point", "131,32")
    foreign = placemark("FOREIGN", "Point", "131,33")
    first_name = "<name>A</name>" if folder_name is not None else ""
    second_name = f"<name>{folder_name}</name>" if folder_name is not None else ""
    text = (f"<kml><Document><Folder>{first_name}{line}{own}</Folder>"
            f"<Folder>{second_name}{foreign}</Folder></Document></kml>")
    assert candidates(text)[0]["routeNames"] == [None, "OWN", None, None]


@pytest.mark.parametrize("junction", ["TURN", None])
def test_connected_names_follow_deduplicated_geometry(junction):
    first = placemark("route", "LineString", "131,31 131,32")
    second = placemark("route", "LineString", "131,32 131,33")
    point = placemark(junction, "Point", "131,32")
    unrelated = placemark("MIDLINE", "Point", "131,31.5")
    candidate = candidates(f"<kml><Document>{first}{second}{point}{unrelated}</Document></kml>")[0]
    assert candidate["kind"] == "connected_lines"
    assert candidate["routeNames"] == [None, junction, None]
    assert candidate["routeCoordinates"] == [[31, 131], [32, 131], [33, 131]]


@pytest.mark.parametrize(("coordinate", "nearby"), [
    ((32, 131), (32.0005, 131)),
    ((0, 179.9998), (0, -179.9998)),
    ((89.9998, 0), (89.9998, 180)),
    ((-89.9998, 0), (-89.9998, 180)),
])
def test_point_name_prefilter_preserves_close_matches_across_dateline_and_poles(
    coordinate, nearby,
):
    result = KmlImportResult(points=(ImportedPoint("NEAR", *nearby),))
    assert AutoNavLogWebApplication._nearest_point_name(result, *coordinate) == "NEAR"


def test_point_name_prefilter_avoids_distant_geodesics_without_changing_match_radius(monkeypatch):
    import autonavlog.web.facade as facade_module

    original = facade_module.geodesic_leg
    calls = []

    def measured(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(facade_module, "geodesic_leg", measured)
    result = KmlImportResult(points=(
        *(ImportedPoint(str(index), 32, 140 + index / 1000) for index in range(200)),
        ImportedPoint("OUTSIDE", 32.002, 131),
    ))
    assert AutoNavLogWebApplication._nearest_point_name(result, 32, 131) is None
    assert len(calls) == 1
