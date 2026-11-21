"""SEA is independent of flight/weather calculation and uses validated terrain inputs."""

from __future__ import annotations

import math
from decimal import ROUND_CEILING, Decimal
from typing import Any
from uuid import UUID

from geographiclib.geodesic import Geodesic
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from autonavlog.domain.project import Project
from autonavlog.nav.geodesy import METERS_PER_NM

from .checkpoints import project_check_points
from .fingerprints import make_fingerprint

POLICY = "sea-3nm-forward-cap-v1"
RADIUS_M = 3 * METERS_PER_NM


class SeaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeaTerrain(SeaModel):
    complete: bool = False
    maximum_m: float | None = Field(default=None, allow_inf_nan=False)
    required: int = Field(default=0, ge=0)
    valid: int = Field(default=0, ge=0)
    missing: int = Field(default=0, ge=0)
    not_acquired: int = Field(default=0, ge=0)
    invalid: int = Field(default=0, ge=0)
    provenance: list[dict[str, Any]] = Field(default_factory=list, max_length=8192)


class SeaRecord(SeaModel):
    terrain: SeaTerrain = Field(default_factory=SeaTerrain)
    kml_maximum_m: float | None = Field(default=None, allow_inf_nan=False)
    manual_ft: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)


class SeaUpdate(SeaModel):
    project_id: UUID
    geometry_key: str
    terrain: dict[str, SeaTerrain] | None = None
    manual: dict[str, float | None] | None = None
    # Already parsed by the #313 boundary. Raw XML is never stored in a Project.
    kml: dict[str, Any] | None = None


def _intervals(project: Project) -> list[dict[str, Any]]:
    nodes = {str(node.id): node for node in project.route_nodes}
    names = {str(ref.id): ref.name for ref in project.visual_references}
    projection = project_check_points(project)
    invalid_sections = {str(issue.section_id) for issue in projection.issues}
    intervals = []
    for section in project.ordered_sections():
        start, end = nodes[str(section.from_node_id)], nodes[str(section.to_node_id)]
        boundaries = [(str(start.id), start.name, start.latitude_deg, start.longitude_deg)]
        boundaries += [
            (
                str(p.checkpoint_id),
                names[str(p.checkpoint_id)],
                p.abeam_latitude_deg,
                p.abeam_longitude_deg,
            )
            for p in projection.projections
            if p.section_id == section.id
        ]
        boundaries.append((str(end.id), end.name, end.latitude_deg, end.longitude_deg))
        for a, b in zip(boundaries, boundaries[1:], strict=False):
            coordinates = [[a[3], a[2]], [b[3], b[2]]]
            key = make_fingerprint(
                kind=POLICY,
                fields={
                    "section_id": str(section.id),
                    "from_id": a[0],
                    "to_id": b[0],
                    "coordinates": coordinates,
                },
            )
            intervals.append(
                {
                    "key": key,
                    "section_id": str(section.id),
                    "from_id": a[0],
                    "to_id": b[0],
                    "from_name": a[1],
                    "to_name": b[1],
                    "coordinates": coordinates,
                    "geometry_valid": str(section.id) not in invalid_sections,
                }
            )
    return intervals


def _regions(coordinates: list[list[float]]) -> list[list[list[float]]]:
    """Short WGS84 strips plus a circumscribed forward end cap.

    1 NM strips bound Mercator chord error in the supported Japanese latitudes;
    2 m outward padding and 5 degree circumscribed cap segments are conservative.
    The start boundary is never shifted backwards. Closed DEM footprints add
    their own raster-scale conservatism. KML uses exact geodesic distance below.
    """
    (lon1, lat1), (lon2, lat2) = coordinates
    if not all(math.isfinite(v) for point in coordinates for v in point):
        return []
    if max(abs(lat1), abs(lat2)) > 50 or abs(lon1 - lon2) >= 180:
        return []
    inverse = Geodesic.WGS84.Inverse(lat1, lon1, lat2, lon2)
    length = inverse["s12"]
    if not 0 < length <= 250 * METERS_PER_NM:
        return []
    line = Geodesic.WGS84.Line(lat1, lon1, inverse["azi1"])
    count = math.ceil(length / METERS_PER_NM)
    stations = [line.Position(length * i / count) for i in range(count + 1)]

    def offset(station: dict[str, float], angle: float, distance: float) -> list[float]:
        p = Geodesic.WGS84.Direct(
            station["lat2"], station["lon2"], station["azi2"] + angle, distance
        )
        return [p["lon2"], p["lat2"]]

    width = RADIUS_M + 2
    regions = [
        [offset(a, -90, width), offset(b, -90, width), offset(b, 90, width), offset(a, 90, width)]
        for a, b in zip(stations, stations[1:], strict=False)
    ]
    cap_radius = width / math.cos(math.radians(2.5))
    regions.append([offset(stations[-1], angle, cap_radius) for angle in range(-90, 91, 5)])
    return regions


def contains_point(coordinates: list[list[float]], point: list[float]) -> bool:
    """Closed 3 NM geodesic corridor; exclude points behind the start plane."""
    (lon1, lat1), (lon2, lat2) = coordinates
    lon, lat = point
    if not all(math.isfinite(v) for v in (lon1, lat1, lon2, lat2, lon, lat)):
        return False
    inverse = Geodesic.WGS84.Inverse(lat1, lon1, lat2, lon2)
    initial = Geodesic.WGS84.Inverse(lat1, lon1, lat, lon)
    if initial["s12"] <= 1e-5:
        return True
    if initial["s12"] > inverse["s12"] + RADIUS_M + 1e-5:
        return False
    if math.cos(math.radians(initial["azi1"] - inverse["azi1"])) < -1e-10:
        return False
    line = Geodesic.WGS84.Line(lat1, lon1, inverse["azi1"])

    def distance(station: float) -> float:
        p = line.Position(station)
        return float(Geodesic.WGS84.Inverse(lat, lon, p["lat2"], p["lon2"])["s12"])

    # A trial station supplies an actual upper bound, never an approximate
    # outside decision. Most interior points need no minimization at all.
    trial = initial["s12"] * math.cos(math.radians(initial["azi1"] - inverse["azi1"]))
    if distance(max(0.0, min(float(inverse["s12"]), trial))) <= RADIUS_M + 1e-5:
        return True
    left, right = 0.0, float(inverse["s12"])
    for _ in range(48):
        a, b = left + (right - left) / 3, right - (right - left) / 3
        da, db = distance(a), distance(b)
        if min(da, db) <= RADIUS_M + 1e-5:
            return True
        # Distance to a fixed point is 1-Lipschitz along the geodesic. This
        # lower bound can reject outside points without exhausting precision.
        lower = max(da - max(a - left, right - a), db - max(b - left, right - b))
        if lower > RADIUS_M + 1e-5:
            return False
        if da < db:
            right = b
        else:
            left = a
    return (
        min(distance(0), distance(inverse["s12"]), distance((left + right) / 2)) <= RADIUS_M + 1e-5
    )


def automatic_sea(record: SeaRecord) -> int | None:
    t = record.terrain
    if (
        not t.complete
        or t.required <= 0
        or t.valid != t.required
        or t.missing
        or t.not_acquired
        or t.invalid
        or t.maximum_m is None
    ):
        return None
    maximum = max(
        t.maximum_m, record.kml_maximum_m if record.kml_maximum_m is not None else -math.inf
    )
    hundreds = Decimal(str(maximum)) / Decimal("30.48")
    return int(hundreds.to_integral_value(rounding=ROUND_CEILING)) * 100 + 1000


def _records(project: Project) -> dict[str, SeaRecord]:
    raw = project.metadata.get("sea", {})
    if not isinstance(raw, dict) or raw.get("policy") != POLICY:
        return {}
    records = {}
    stored = raw.get("records")
    if not isinstance(stored, dict):
        return {}
    for key, value in stored.items():
        try:
            records[key] = SeaRecord.model_validate(value)
        except (ValidationError, TypeError):
            pass  # Damaged optional SEA data must not stop flight calculations.
    return records


def sea_plan(project: Project, *, regions: bool = False) -> dict[str, Any]:
    intervals = _intervals(project)
    records = _records(project)
    for item in intervals:
        record = records.get(item["key"], SeaRecord()) if item["geometry_valid"] else SeaRecord()
        auto = automatic_sea(record)
        item.update(
            {
                "automatic_ft": auto,
                "manual_ft": record.manual_ft,
                "value_ft": record.manual_ft if record.manual_ft is not None else auto,
                "status": "manual"
                if record.manual_ft is not None
                else "automatic"
                if auto is not None
                else "unknown",
                "warning": "below-automatic"
                if record.manual_ft is not None and auto is not None and record.manual_ft < auto
                else "unconfirmed"
                if record.manual_ft is None and auto is None
                else None,
                "terrain": record.terrain.model_dump(mode="json"),
            }
        )
        if regions:
            item["regions"] = _regions(item["coordinates"]) if item["geometry_valid"] else []
    raw = project.metadata.get("sea")
    kml = raw.get("kml") if isinstance(raw, dict) else None
    provenance = kml.get("provenance") if isinstance(kml, dict) else None
    kml_source = None
    if isinstance(provenance, dict):
        kml_source = {
            name: str(provenance.get(name, ""))
            for name in (
                "source",
                "verticalReference",
                "demCompatibilityEvidence",
                "importedAt",
                "sha256",
            )
        }
    return {
        "geometry_key": make_fingerprint(
            kind=POLICY, fields={"keys": [[i["key"], i["geometry_valid"]] for i in intervals]}
        ),
        "intervals": intervals,
        "kml_source": kml_source,
    }


def apply_sea(project: Project, update: SeaUpdate) -> None:
    plan = sea_plan(project)
    if project.id != update.project_id or plan["geometry_key"] != update.geometry_key:
        raise ValueError("stale-sea-geometry")
    records = _records(project)
    current = {item["key"]: item for item in plan["intervals"]}
    if set(update.terrain or {}) - current.keys() or set(update.manual or {}) - current.keys():
        raise ValueError("unknown-sea-interval")
    previous_keys = set(records)
    records = {key: records.get(key, SeaRecord()) for key in current}
    for key, terrain in (update.terrain or {}).items():
        records[key].terrain = terrain
    for key, manual in (update.manual or {}).items():
        records[key] = SeaRecord.model_validate({**records[key].model_dump(), "manual_ft": manual})
    previous = project.metadata.get("sea", {})
    kml = (
        update.kml
        if update.kml is not None
        else previous.get("kml")
        if isinstance(previous, dict)
        else None
    )
    points = []
    if isinstance(kml, dict) and kml.get("status") in ("available", "partial"):
        provenance = kml.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        if (
            provenance.get("meaning") == "terrain"
            and provenance.get("verticalReference") == "TP"
            and provenance.get("source")
            and provenance.get("demCompatibilityEvidence")
        ):
            raw_points = kml.get("points")
            points = raw_points if isinstance(raw_points, list) and len(raw_points) <= 10000 else []
    candidates = []
    for point in points:
        try:
            elevation = float(point["elevationM"])
            coordinate = point["coordinate"]
            if (
                math.isfinite(elevation)
                and len(coordinate) == 2
                and abs(coordinate[0]) <= 180
                and abs(coordinate[1]) <= 90
            ):
                candidates.append((elevation, coordinate))
        except (KeyError, TypeError, ValueError):
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    for key, record in records.items():
        if update.kml is None and key in previous_keys:
            continue
        vertices = [point for region in _regions(current[key]["coordinates"]) for point in region]
        if not vertices or not candidates:
            record.kml_maximum_m = None
            continue
        west, east = min(p[0] for p in vertices), max(p[0] for p in vertices)
        south, north = min(p[1] for p in vertices), max(p[1] for p in vertices)
        # Only the highest in-region point matters. Inspect descending values
        # and avoid 10,000 geodesic searches for a dense terrain survey.
        record.kml_maximum_m = next(
            (
                elevation
                for elevation, coordinate in candidates
                if west <= coordinate[0] <= east
                and south <= coordinate[1] <= north
                and contains_point(current[key]["coordinates"], coordinate)
            ),
            None,
        )
    project.metadata["sea"] = {
        "policy": POLICY,
        "kml": kml,
        "records": {key: value.model_dump(mode="json") for key, value in records.items()},
    }


def prune_sea(project: Project) -> None:
    raw = project.metadata.get("sea")
    if not isinstance(raw, dict):
        return
    keys = {item["key"] for item in _intervals(project)}
    raw["records"] = {
        key: value.model_dump(mode="json")
        for key, value in _records(project).items()
        if key in keys
    }
