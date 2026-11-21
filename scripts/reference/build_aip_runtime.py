"""Normalize the registered EFF20261029 map sources; never repair or infer aviation data."""

import argparse
import hashlib
import io
import json
import math
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile

import shapefile
from defusedxml import ElementTree
from shapely import get_coordinates, normalize
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
DATASET = "data/reference/aip/20261029"
NS = {"k": "http://www.opengis.net/kml/2.2"}
PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]]'
)
VERTICAL_PRJ = (
    ',VERTCS["WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PARAMETER["Vertical_Shift",0.0],PARAMETER["Direction",1.0],UNIT["Meter",1.0]]'
)
# Source record / Placemark indices are zero-based. These are observed format
# differences, not instructions to combine vertical bands in the runtime dataset.
EXCEPTIONS = {
    "Approach_control_area_CIVIL": {87: [36], 88: [37]},
    "Approach_control_area_MIL": {
        67: [7],
        68: [8],
        69: [73],
        70: [74],
        71: [26, 77],
        72: [25, 76],
        73: [41, 78],
        74: [24, 75],
    },
}


def encoded(value):
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def vertical_limit(raw):
    """A bare FT value does not establish its vertical datum; blanks are not SFC."""
    result = {
        "raw": raw,
        "status": "uninterpreted",
        "value": None,
        "unit": None,
        "reference": "unspecified",
    }
    if raw is None or not raw.strip():
        result["status"] = "missing"
    elif raw in ("SFC", "GND"):
        result.update(status="surface", reference="surface")
    elif raw == "UNL":
        result["status"] = "unlimited"
    elif match := re.fullmatch(r"FL(\d+)", raw):
        result.update(
            status="parsed", value=int(match[1]), unit="FL", reference="standard_pressure"
        )
    elif match := re.fullmatch(r"(\d+)FT(?: (AGL|AMSL|MSL))?", raw):
        result.update(
            status="parsed",
            value=int(match[1]),
            unit="FT",
            reference={"AGL": "AGL", "AMSL": "MSL", "MSL": "MSL"}.get(match[2], "unspecified"),
        )
    return result


def validate_geometry(geometry):
    require(not geometry.is_empty and geometry.is_valid, "Empty or invalid geometry")
    coordinates = get_coordinates(geometry)
    require(
        len(coordinates) > 0
        and all(
            math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90
            for x, y in coordinates
        ),
        "Invalid WGS84 coordinates",
    )


class DescriptionTable(HTMLParser):
    """Read the source's two-cell attribute rows as text, never emit its HTML/script."""

    def __init__(self, text):
        super().__init__()
        self.attributes = {}
        self.row = []
        self.cell = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag == "td":
            self.cell = ""

    def handle_data(self, text):
        if self.cell is not None:
            self.cell += text

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        if tag == "tr" and len(self.row) == 2:
            key, value = self.row
            require(key not in self.attributes, "Duplicate KML attribute")
            self.attributes[key] = value
            self.row = []


def kml_geometry(placemark):
    def coordinates(node):
        require(node is not None and bool(node.text), "Missing KML coordinates")
        values = [list(map(float, value.split(","))) for value in node.text.split()]
        require(
            all(len(value) in (2, 3) and all(math.isfinite(n) for n in value) for value in values),
            "Invalid KML position",
        )
        return [value[:2] for value in values]

    polygons = []
    for polygon in placemark.findall(".//k:Polygon", NS):
        outer = coordinates(polygon.find("k:outerBoundaryIs/k:LinearRing/k:coordinates", NS))
        holes = [
            coordinates(node)
            for node in polygon.findall("k:innerBoundaryIs/k:LinearRing/k:coordinates", NS)
        ]
        require(all(ring[0] == ring[-1] for ring in [outer, *holes]), "Unclosed KML ring")
        polygons.append(Polygon(outer, holes))
    points = placemark.findall(".//k:Point/k:coordinates", NS)
    lines = placemark.findall(".//k:LineString/k:coordinates", NS)
    require(
        sum(bool(group) for group in (polygons, points, lines)) == 1, "Empty or mixed KML geometry"
    )
    if polygons:
        geometry = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
    elif points:
        require(len(points) == 1 and len(coordinates(points[0])) == 1, "Invalid KML point")
        geometry = Point(coordinates(points[0])[0])
    else:
        from shapely.geometry import MultiLineString

        geometry = (
            LineString(coordinates(lines[0]))
            if len(lines) == 1
            else MultiLineString([coordinates(node) for node in lines])
        )
    validate_geometry(geometry)
    return geometry


def source_ordinates(source_shape):
    """Keep source Z/M separately from map geometry and aviation vertical limits."""
    if not hasattr(source_shape, "z") and not hasattr(source_shape, "m"):
        return None
    points = [list(point) for point in source_shape.points]
    ordinates = {}
    for axis in ("z", "m"):
        values = list(getattr(source_shape, axis)) if hasattr(source_shape, axis) else None
        require(
            values is None
            or (
                len(values) == len(points)
                and all(value is None or math.isfinite(value) for value in values)
            ),
            "Invalid source Z/M ordinates",
        )
        ordinates[axis] = values
    return {
        "shape_type": source_shape.shapeType,
        # XY is needed here: polygon ring grouping in GeoJSON need not retain
        # the original Shapefile point/part order used by the ordinate arrays.
        "points": points,
        "parts": list(getattr(source_shape, "parts", [])),
        **ordinates,
        "interpretation": "uninterpreted_source_ordinates_not_vertical_limits",
    }


def read_shape_layer(archive, layer):
    stem = f"Shapefile_20261029/{layer}_EFF20261029"
    require(
        archive.read(stem + ".prj").decode() in (PRJ, PRJ + VERTICAL_PRJ), "Unexpected source CRS"
    )
    require(archive.read(stem + ".cpg") == b"UTF-8", "Unexpected source encoding")
    with shapefile.Reader(
        **{ext: io.BytesIO(archive.read(stem + "." + ext)) for ext in ("shp", "shx", "dbf")},
        encoding="utf-8",
    ) as reader:
        rows = []
        seen = set()
        for index, record in enumerate(reader.iterShapeRecords()):
            require(record.shape.shapeType != shapefile.NULL, "Empty Shapefile geometry")
            raw = record.record.as_dict()
            geometry = shape(record.shape.__geo_interface__)
            validate_geometry(geometry)
            ordinates = source_ordinates(record.shape)
            # Equal horizontal geometry at different heights is not a duplicate.
            key = (normalize(geometry).wkb, encoded(raw))
            if ordinates:
                # Coordinate/ordinate associations, independent of ring direction.
                points = ordinates["points"]
                key += (
                    tuple(
                        sorted(
                            encoded([point, z, m])
                            for point, z, m in zip(
                                points,
                                ordinates["z"] or [None] * len(points),
                                ordinates["m"] or [None] * len(points),
                                strict=True,
                            )
                        )
                    ),
                )
            require(key not in seen, f"Duplicate source feature: {layer}:{index}")
            seen.add(key)
            rows.append((raw, geometry, ordinates))
        require(len(rows) == reader.numRecords, "Deleted or missing Shapefile records")
        return rows


def read_kml_layer(archive, layer):
    member = f"KML_20261029/{layer}_EFF20261029.kml"
    tree = ElementTree.fromstring(archive.read(member))
    rows = []
    seen = set()
    for placemark in tree.findall(".//k:Placemark", NS):
        raw = DescriptionTable(placemark.findtext("k:description", "", NS)).attributes
        geometry = kml_geometry(placemark)
        key = (normalize(geometry).wkb, encoded(raw))
        require(key not in seen, f"Duplicate KML feature: {layer}")
        seen.add(key)
        rows.append((raw, geometry))
    return rows


def reconcile_approach(layer, shapes, kml):
    """Verify unchanged rows and retain exact exceptions, including geometric discrepancies."""
    exceptions = EXCEPTIONS[layer]
    used = set()
    differences = []
    for index, (attributes, geometry) in enumerate(kml):
        candidates = exceptions.get(index)
        if candidates is None:
            candidates = [
                i
                for i, (raw, geom, _) in enumerate(shapes)
                if raw == attributes and geom.equals_exact(geometry, 1e-9, normalize=True)
            ]
            require(len(candidates) == 1, f"Unexpected format difference: {layer}:{index}")
        else:
            differences.append(
                {
                    "kml_placemark_index": index,
                    "kml_attributes": attributes,
                    "shapefile_records": [
                        {
                            "record_index": i,
                            "attributes": shapes[i][0],
                            "horizontal_geometry_equal_1e_9_degree": shapes[i][1].equals_exact(
                                geometry, 1e-9, normalize=True
                            ),
                        }
                        for i in candidates
                    ],
                }
            )
        require(not used.intersection(candidates), "Shapefile record reconciled twice")
        used.update(candidates)
    unmatched = sorted(set(range(len(shapes))) - used)
    require(
        unmatched == ([14] if layer.endswith("CIVIL") else []),
        "Unexpected unmatched source records",
    )
    # KML combines labels/vertical ranges. Even their horizontal unions are not
    # byte/geometrically identical to these SHP records; do not claim equivalence.
    comparisons = [(14, [87, 88])] if layer.endswith("CIVIL") else [(73, [69, 67]), (74, [70, 68])]
    return {
        "layer_id": layer,
        "shapefile_count": len(shapes),
        "kml_count": len(kml),
        "runtime_basis": "Shapefile; no merge, deduplication, or vertical inference",
        "differences": differences,
        "shapefile_without_individual_kml_placemark": [
            {"record_index": i, "attributes": shapes[i][0]} for i in unmatched
        ],
        "horizontal_union_comparisons": [
            {
                "shapefile_record_index": i,
                "kml_placemark_indices": indices,
                "equal": shapes[i][1].equals(unary_union([kml[j][1] for j in indices])),
                "symmetric_difference_square_degrees": shapes[i][1]
                .symmetric_difference(unary_union([kml[j][1] for j in indices]))
                .area,
            }
            for i, indices in comparisons
        ],
        "interpretation": "KML combines named controls and/or disjoint vertical bands; "
        "Hiroshima and Sapporo also have horizontal differences. "
        "The formats are not interchangeable; source attributes remain separate.",
    }


def feature(layer, index, raw, geometry, ordinates, dataset):
    label_field = next(
        (
            key
            for key in (
                "NAME",
                "NAME1",
                "ID_NAME",
                "NAME_CODE",
                "CS",
                "HLDG_POINT",
                "DESIGNATOR",
                "ICAO_ID",
                "ID",
                "AD",
            )
            if raw.get(key)
        ),
        None,
    )
    return {
        "type": "Feature",
        "id": f"{dataset}:{layer}:{index}",
        "geometry": mapping(geometry),
        "properties": {
            "layer_id": layer,
            "label": raw[label_field] if label_field else None,
            "label_field": label_field,
            "source_record_index": index,
            "source_attributes": raw,
            "source_geometry_ordinates": ordinates,
            "vertical_limits": {
                "lower": vertical_limit(raw.get("ALT_LOWER")),
                "upper": vertical_limit(raw.get("ALT_UPPER")),
                "qualifications": {
                    key: value
                    for key, value in raw.items()
                    if key in ("RMK_ALT", "RMKS", "REMARKS") and value
                },
                "interpretation": "source_limits_only_not_operational_clearance",
            },
        },
    }


def build(root, output):
    source = root / DATASET
    source_bytes = (source / "source_manifest.json").read_bytes()
    manifest = json.loads(source_bytes)
    archives = {}
    try:
        for entry in manifest["source_archives"]:
            data = (source / "sources" / entry["filename"]).read_bytes()
            require(
                len(data) == entry["size_bytes"] and digest(data) == entry["sha256"],
                f"Source archive integrity failure: {entry['filename']}",
            )
            archive = ZipFile(io.BytesIO(data))
            require(archive.testzip() is None, "Source archive CRC failure")
            require(len(set(archive.namelist())) == len(archive.namelist()), "Duplicate ZIP member")
            archives[entry["filename"]] = archive
        shp = archives["Shapefile_20261029.zip"]
        kml = archives["KML_20261029.zip"]
        layers = manifest["layers"]
        expected_layers = {entry["id"] for entry in layers}
        for archive, ext in ((shp, ".shp"), (kml, ".kml")):
            actual = {
                Path(name).stem.removesuffix("_EFF20261029")
                for name in archive.namelist()
                if name.endswith(ext)
            }
            require(actual == expected_layers, "Unexpected or missing source layer")
        files = {}
        counts = []
        reconciliation = []
        for entry in layers:
            layer = entry["id"]
            shapes = read_shape_layer(shp, layer)
            kml_rows = read_kml_layer(kml, layer)
            expected_kml = next(
                (
                    row["kml_placemark_count"]
                    for row in manifest["kml_shapefile_count_differences"]
                    if row["layer_id"] == layer
                ),
                entry["feature_count"],
            )
            require(
                len(shapes) == entry["feature_count"] and len(kml_rows) == expected_kml,
                f"Source count mismatch: {layer}",
            )
            if layer in EXCEPTIONS:
                reconciliation.append(reconcile_approach(layer, shapes, kml_rows))
            collection = {
                "type": "FeatureCollection",
                "dataset_id": manifest["dataset_id"],
                "effective_date": manifest["effective_date"],
                "layer_id": layer,
                "features": [
                    feature(layer, i, raw, geometry, ordinates, manifest["dataset_id"])
                    for i, (raw, geometry, ordinates) in enumerate(shapes)
                ],
            }
            data = encoded(collection)
            # Validate the serialized geometry as well as the source geometry.
            for row in json.loads(data)["features"]:
                validate_geometry(shape(row["geometry"]))
            name = f"{layer}-{digest(data)}.geojson"
            files[name] = data
            counts.append(
                {
                    "id": layer,
                    "feature_count": len(shapes),
                    "kml_count": len(kml_rows),
                    "file": name,
                    "sha256": digest(data),
                    "bytes": len(data),
                    "source_members": {
                        "geometry": f"Shapefile_20261029/{layer}_EFF20261029.shp",
                        "attributes": f"Shapefile_20261029/{layer}_EFF20261029.dbf",
                        "comparison": f"KML_20261029/{layer}_EFF20261029.kml",
                    },
                    "geometry_types": dict(
                        sorted(Counter(g.geom_type for _, g, _ in shapes).items())
                    ),
                }
            )
        require(
            sum(row["kml_count"] for row in counts) == manifest["kml_feature_count"],
            "KML total mismatch",
        )
    finally:
        for archive in archives.values():
            archive.close()
    report = encoded(reconciliation)
    report_name = f"reconciliation-{digest(report)}.json"
    files[report_name] = report
    result = {
        "schema_version": 1,
        "dataset_id": manifest["dataset_id"],
        "app_version": (root / "VERSION").read_text().strip(),
        "effective_date": manifest["effective_date"],
        "coordinate_system": "WGS84 longitude/latitude",
        "publisher": manifest["publisher"],
        "sources": manifest["sources"],
        "source_manifest_sha256": digest(source_bytes),
        "source_archives": manifest["source_archives"],
        "processing": {
            "script": "scripts/reference/build_aip_runtime.py",
            "sha256": digest(Path(__file__).read_bytes()),
            "steps": [
                "Verify archive SHA-256, size, CRC, CRS and UTF-8 encoding",
                "Validate all 25 SHP and KML layers; reject invalid/empty/duplicate features",
                "Use Shapefile geometry and attributes in source record order",
                "Export 2D GeoJSON without simplification or geometry repair; "
                "preserve source XY, part offsets and Z/M arrays separately without "
                "interpreting them as vertical limits",
                "Keep raw attributes; parse only explicit altitude syntax; "
                "do not infer a datum for bare FT values or interpret remarks",
                "Reconcile approach-control format differences without merging records",
            ],
        },
        "limitations": {
            "TCA": "not_provided",
            "ACA": "mapping_unconfirmed",
            "NOTAM": "not_supported",
            "current_activation": "not_supported",
        },
        "display_date_policy": manifest["display_date_policy"],
        "feature_count": sum(row["feature_count"] for row in counts),
        "kml_placemark_count": sum(row["kml_count"] for row in counts),
        "layers": counts,
        "reconciliation": {"file": report_name, "sha256": digest(report), "bytes": len(report)},
    }
    data = encoded(result)
    name = f"manifest-{digest(data)}.json"
    files[name] = data
    output.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (output / filename).write_bytes(content)
    return {"file": f"reference/aip/{name}", "sha256": digest(data), "bytes": len(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-root", type=Path, default=ROOT / "web/public-local")
    args = parser.parse_args()
    local_manifest = args.public_root / "local/manifest.json"
    local = json.loads(local_manifest.read_text())
    require(local["version"] == (ROOT / "VERSION").read_text().strip(), "Local version mismatch")
    local["mapReference"] = build(ROOT, args.public_root / "reference/aip")
    local_manifest.write_bytes(encoded(local))
    print("AIP reference: 25 layers / 5276 Shapefile records / 5271 KML Placemarks")


if __name__ == "__main__":
    main()
