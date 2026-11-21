"""Registered AIP inputs, normalization, and the calculation-data boundary."""

import io
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
import shapefile
from shapely.geometry import Point, Polygon, shape

from autonavlog.forecast_backup import calculation_contract
from scripts.reference.build_aip_runtime import (
    DATASET,
    PRJ,
    build,
    digest,
    encoded,
    read_kml_layer,
    read_shape_layer,
    validate_geometry,
    vertical_limit,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def normalized(tmp_path_factory):
    output = tmp_path_factory.mktemp("aip")
    descriptor = build(ROOT, output)
    manifest = json.loads((output / Path(descriptor["file"]).name).read_bytes())
    return output, descriptor, manifest


def test_registered_sources_are_reproducible_and_traceable(normalized, tmp_path):
    output, descriptor, manifest = normalized
    assert build(ROOT, tmp_path) == descriptor
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {
        p.name: p.read_bytes() for p in tmp_path.iterdir()
    }
    assert manifest["feature_count"] == 5276
    assert manifest["kml_placemark_count"] == 5271
    assert manifest["app_version"] == (ROOT / "VERSION").read_text().strip()
    assert manifest["effective_date"] == "2026-10-29"
    assert len(manifest["layers"]) == 25
    assert manifest["source_manifest_sha256"] == digest(
        (ROOT / DATASET / "source_manifest.json").read_bytes()
    )
    assert manifest["processing"]["sha256"] == digest(
        (ROOT / "scripts/reference/build_aip_runtime.py").read_bytes()
    )
    ids = set()
    for entry in [*manifest["layers"], manifest["reconciliation"]]:
        content = (output / entry["file"]).read_bytes()
        assert len(content) == entry["bytes"] and digest(content) == entry["sha256"]
        if "id" not in entry:
            continue
        features = json.loads(content)["features"]
        assert len(features) == entry["feature_count"]
        for row in features:
            assert row["id"] not in ids
            ids.add(row["id"])
            validate_geometry(shape(row["geometry"]))
    assert len(ids) == 5276
    assert manifest["limitations"] == {
        "TCA": "not_provided",
        "ACA": "mapping_unconfirmed",
        "NOTAM": "not_supported",
        "current_activation": "not_supported",
    }
    assert manifest["display_date_policy"] == "NO_DATE_BASED_VISIBILITY_RESTRICTION"
    assert not any(layer["id"] in ("TCA", "ACA") for layer in manifest["layers"])


def test_format_discrepancies_are_preserved_not_force_merged(normalized):
    output, _, manifest = normalized
    reports = json.loads((output / manifest["reconciliation"]["file"]).read_bytes())
    civil, military = reports
    assert (civil["shapefile_count"], civil["kml_count"]) == (94, 93)
    assert (military["shapefile_count"], military["kml_count"]) == (79, 75)
    assert [row["kml_placemark_index"] for row in civil["differences"]] == [87, 88]
    assert (
        civil["shapefile_without_individual_kml_placemark"][0]["attributes"]["NAME"] == "Hiroshima"
    )
    assert [row["kml_placemark_index"] for row in military["differences"]] == list(range(67, 75))
    assert [len(row["shapefile_records"]) for row in military["differences"]] == [1] * 4 + [2] * 4
    assert all(
        not row["equal"] and row["symmetric_difference_square_degrees"] > 0
        for report in reports
        for row in report["horizontal_union_comparisons"]
    )
    # The four military pairs have identical footprints but distinct vertical attributes.
    assert all(
        row["horizontal_geometry_equal_1e_9_degree"]
        for diff in military["differences"][4:]
        for row in diff["shapefile_records"]
    )


@pytest.mark.parametrize(
    ("raw", "status", "unit", "reference", "value"),
    [
        (None, "missing", None, "unspecified", None),
        ("", "missing", None, "unspecified", None),
        ("-", "uninterpreted", None, "unspecified", None),
        ("SFC", "surface", None, "surface", None),
        ("GND", "surface", None, "surface", None),
        ("UNL", "unlimited", None, "unspecified", None),
        ("FL150", "parsed", "FL", "standard_pressure", 150),
        ("6000FT", "parsed", "FT", "unspecified", 6000),
        ("1700FT AGL", "parsed", "FT", "AGL", 1700),
        (
            "2200-0730 FL260,0730-0930 FL240, Above : by NOTAM",
            "uninterpreted",
            None,
            "unspecified",
            None,
        ),
    ],
)
def test_vertical_limits_do_not_infer_missing_semantics(raw, status, unit, reference, value):
    assert vertical_limit(raw) == {
        "raw": raw,
        "status": status,
        "unit": unit,
        "reference": reference,
        "value": value,
    }


def test_ks4_bands_are_not_duplicated_and_notes_survive(normalized):
    output, _, manifest = normalized
    entry = next(
        row for row in manifest["layers"] if row["id"] == "Civil_training_and_testing_areas"
    )
    features = json.loads((output / entry["file"]).read_bytes())["features"]
    ks4 = [row for row in features if row["properties"]["label"].startswith("KS4-")]
    assert len(ks4) == 8
    row = next(row["properties"] for row in ks4 if row["properties"]["label"] == "KS4-3")
    assert row["vertical_limits"]["qualifications"]["RMK_ALT"] == (
        "KS4-3-30:SFC-3000FT,KS4-3-45:3000FT-4500FT,KS4-3-60:4500FT-6000FT"
    )
    assert row["source_attributes"]["ALT_UPPER"] == "6000FT"


def test_nonzero_source_z_and_missing_m_survive_without_becoming_vertical_limits(normalized):
    output, _, manifest = normalized
    layer = "Take_off_flight_path_area"
    entry = next(row for row in manifest["layers"] if row["id"] == layer)
    features = json.loads((output / entry["file"]).read_bytes())["features"]
    with ZipFile(ROOT / DATASET / "sources/Shapefile_20261029.zip") as archive:
        stem = f"Shapefile_20261029/{layer}_EFF20261029"
        with shapefile.Reader(
            **{ext: io.BytesIO(archive.read(stem + "." + ext)) for ext in ("shp", "shx", "dbf")}
        ) as reader:
            originals = reader.shapes()
    assert any(value > 1 for original in originals for value in original.z)
    for feature, original in zip(features, originals, strict=True):
        props = feature["properties"]
        saved = props["source_geometry_ordinates"]
        assert saved["z"] == list(original.z)
        assert saved["m"] == list(original.m)
        assert saved["points"] == [list(point) for point in original.points]
        assert saved["parts"] == list(original.parts)
        assert saved["shape_type"] == 15
        assert props["vertical_limits"]["lower"]["status"] == "missing"
        assert props["vertical_limits"]["upper"]["status"] == "missing"
    assert any(value is None for original in originals for value in original.m)


@pytest.mark.parametrize(
    "geometry",
    [
        Point(),
        Point(float("nan"), 0),
        Point(181, 0),
        Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)]),
    ],
)
def test_bad_geometry_is_rejected(geometry):
    with pytest.raises(ValueError):
        validate_geometry(geometry)


def shape_archive(records, *, crs=PRJ, shape_type=shapefile.POINT):
    buffers = {name: io.BytesIO() for name in ("shp", "shx", "dbf")}
    with shapefile.Writer(**buffers, shapeType=shape_type) as writer:
        writer.field("NAME", "C")
        for name, coordinates in records:
            if coordinates is None:
                writer.null()
            elif shape_type == shapefile.POLYGONZ:
                writer.polyz(coordinates)
            else:
                writer.point(*coordinates)
            writer.record(name)
    archive = io.BytesIO()
    stem = "Shapefile_20261029/Test_EFF20261029"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zipped:
        for name, buffer in buffers.items():
            zipped.writestr(stem + "." + name, buffer.getvalue())
        zipped.writestr(stem + ".prj", crs)
        zipped.writestr(stem + ".cpg", "UTF-8")
    return ZipFile(archive)


def polygon_z_rings():
    # Clockwise shell, counterclockwise hole, varying Z/M at each vertex.
    return [
        [[x, y, 100 + i, 200 + i] for i, (x, y) in enumerate(ring)]
        for ring in (
            [(0, 0), (0, 4), (4, 4), (4, 0)],
            [(1, 1), (2, 1), (2, 2), (1, 2)],
        )
    ]


@pytest.mark.parametrize("offset", [1, 2])
def test_polygon_z_duplicate_rejects_rotated_ring_start(offset):
    rings = polygon_z_rings()
    rotated = [ring[offset:] + ring[:offset] for ring in rings]

    def close(parts):
        return [ring + [ring[0]] for ring in parts]

    with shape_archive(
        [("same", close(rings)), ("same", close(rotated))], shape_type=shapefile.POLYGONZ
    ) as archive:
        with pytest.raises(ValueError, match="Duplicate source feature"):
            read_shape_layer(archive, "Test")


@pytest.mark.parametrize("axis", [2, 3])
@pytest.mark.parametrize("vertex", [1, -1])
def test_polygon_z_distinct_ordinates_and_original_closed_arrays_survive(axis, vertex):
    rings = polygon_z_rings()
    first = [ring + [ring[0]] for ring in rings]
    second = [[point.copy() for point in ring] for ring in first]
    second[1][vertex][axis] += 10
    with shape_archive(
        [("same", first), ("same", second)], shape_type=shapefile.POLYGONZ
    ) as archive:
        rows = read_shape_layer(archive, "Test")
    assert len(rows) == 2
    for (_, _, ordinates), parts in zip(rows, (first, second), strict=True):
        vertices = [point for ring in parts for point in ring]
        assert ordinates["points"] == [point[:2] for point in vertices]
        assert ordinates["z"] == [point[2] for point in vertices]
        assert ordinates["m"] == [point[3] for point in vertices]
        assert ordinates["parts"] == [0, 5]


@pytest.mark.parametrize(
    "records,crs",
    [
        ([("duplicate", (1, 1)), ("duplicate", (1, 1))], PRJ),
        ([("empty", None)], PRJ),
        ([("bad", (181, 0))], PRJ),
        ([("point", (1, 1))], "unknown CRS"),
    ],
)
def test_bad_shapefile_records_do_not_become_valid_data(records, crs):
    with shape_archive(records, crs=crs) as archive, pytest.raises(ValueError):
        read_shape_layer(archive, "Test")


def test_duplicate_kml_is_rejected():
    placemark = "<Placemark><Point><coordinates>1,2,0</coordinates></Point></Placemark>"
    archive = io.BytesIO()
    with ZipFile(archive, "w") as zipped:
        zipped.writestr(
            "KML_20261029/Test_EFF20261029.kml",
            '<kml xmlns="http://www.opengis.net/kml/2.2">' + placemark * 2 + "</kml>",
        )
    with ZipFile(archive) as zipped, pytest.raises(ValueError, match="Duplicate KML"):
        read_kml_layer(zipped, "Test")


def test_source_checksum_failure_stops_normalization(tmp_path):
    source = tmp_path / DATASET
    (source / "sources").mkdir(parents=True)
    (source / "source_manifest.json").write_bytes(
        (ROOT / DATASET / "source_manifest.json").read_bytes()
    )
    (source / "sources/KML_20261029.zip").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity failure"):
        build(tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_map_reference_does_not_change_calculation_fingerprint(tmp_path, normalized):
    # runtime_data_files deliberately excludes the whole reference/aip tree.
    from autonavlog.runtime_data import runtime_data_files

    before = calculation_contract(tmp_path)
    path = tmp_path / "reference/aip/runtime/manifest.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(encoded(normalized[2]))
    calculation_contract.cache_clear()
    assert calculation_contract(tmp_path) == before
    assert list(runtime_data_files(tmp_path)) == []
    assert not any(
        path.is_relative_to(ROOT / DATASET) for path in runtime_data_files(ROOT / "data")
    )
