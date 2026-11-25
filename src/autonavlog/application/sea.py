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

LEGACY_POLICY = "sea-3nm-forward-cap-v1"
POLICY = "sea-3nm-strips-turns-v2"
RADIUS_M = 3 * METERS_PER_NM


class SeaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeaTerrain(SeaModel):
    complete: bool = False
    # Old incomplete records stopped early; only new full evaluations qualify.
    evaluated: bool = False
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


def _turns(project: Project) -> dict[str, dict[str, Any]]:
    """One shared outer sector at each connected physical turn."""
    nodes = {str(node.id): node for node in project.route_nodes}
    sections = project.ordered_sections()
    turns = {}
    for incoming, outgoing in zip(sections, sections[1:], strict=False):
        if incoming.to_node_id != outgoing.from_node_id:
            continue
        a, b, c = (nodes[str(key)] for key in (
            incoming.from_node_id, incoming.to_node_id, outgoing.to_node_id
        ))
        before = _supported_inverse([[a.longitude_deg, a.latitude_deg],
                                     [b.longitude_deg, b.latitude_deg]], maximum_nm=math.inf)
        after = _supported_inverse([[b.longitude_deg, b.latitude_deg],
                                    [c.longitude_deg, c.latitude_deg]], maximum_nm=math.inf)
        if before is None or after is None:
            continue
        angle = (after["azi1"] - before["azi2"] + 180) % 360 - 180
        if abs(angle) < 1e-8:
            continue
        turns[str(b.id)] = {
            "center": [b.longitude_deg, b.latitude_deg],
            "bearing": before["azi2"] + (-90 if angle > 0 else 90),
            "angle": angle,
        }
    return turns


def _intervals(project: Project, *, legacy: bool = False) -> list[dict[str, Any]]:
    nodes = {str(node.id): node for node in project.route_nodes}
    names = {str(ref.id): ref.name for ref in project.visual_references}
    projection = project_check_points(project)
    invalid_sections = {str(issue.section_id) for issue in projection.issues}
    turns = {} if legacy else _turns(project)
    intervals = []
    for section in project.ordered_sections():
        start, end = nodes[str(section.from_node_id)], nodes[str(section.to_node_id)]
        leg = [[start.longitude_deg, start.latitude_deg], [end.longitude_deg, end.latitude_deg]]
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
            sectors = [turns[key] for key in (a[0], b[0]) if key in turns]
            fields: dict[str, Any] = {
                "section_id": str(section.id), "from_id": a[0], "to_id": b[0],
                "coordinates": coordinates,
            }
            if not legacy:
                fields.update(leg=leg, turns=sectors)
            key = make_fingerprint(
                kind=LEGACY_POLICY if legacy else POLICY, fields=fields,
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
                    "leg_coordinates": leg,
                    "turns": sectors,
                    "geometry_valid": str(section.id) not in invalid_sections,
                }
            )
    return intervals


def _supported_inverse(
    coordinates: list[list[float]], *, maximum_nm: float = 250,
) -> dict[str, float] | None:
    """Share the acquisition range with adoption of posted and saved evidence."""
    (lon1, lat1), (lon2, lat2) = coordinates
    if not all(math.isfinite(v) for point in coordinates for v in point):
        return None
    if max(abs(lat1), abs(lat2)) > 50 or abs(lon1 - lon2) >= 180:
        return None
    inverse = Geodesic.WGS84.Inverse(lat1, lon1, lat2, lon2)
    return inverse if 0 < inverse["s12"] <= maximum_nm * METERS_PER_NM else None


def _regions(
    coordinates: list[list[float]], leg: list[list[float]] | None = None,
) -> list[list[list[float]]]:
    """WGS84 strips anchored to the physical leg, clipped at exact CP planes.

    1 NM strips bound Mercator chord error in the supported Japanese latitudes;
    2 m outward padding is conservative. Neither endpoint is extended.
    CP edits change only the strips intersected by their boundaries. DEM footprints add
    their own raster-scale conservatism. KML uses exact geodesic distance below.
    """
    leg = leg or coordinates
    inverse = _supported_inverse(leg, maximum_nm=math.inf)
    if inverse is None or _supported_inverse(coordinates) is None:
        return []
    (lon1, lat1), _ = leg
    length = inverse["s12"]
    line = Geodesic.WGS84.Line(lat1, lon1, inverse["azi1"])
    left, right = [Geodesic.WGS84.Inverse(lat1, lon1, lat, lon)["s12"]
                   for lon, lat in coordinates]
    right = min(right, length)
    # Coalesce an interior grid cut within geodesic round-trip noise of an
    # endpoint. Keep the actual CP/end station; never snap it to the grid.
    cuts = [left] + [i * METERS_PER_NM
                     for i in range(1, math.ceil(length / METERS_PER_NM))
                     if left + 1e-6 < i * METERS_PER_NM < right - 1e-6] + [right]
    stations = [line.Position(distance) for distance in cuts]

    def offset(station: dict[str, float], angle: float, distance: float) -> list[float]:
        p = Geodesic.WGS84.Direct(
            station["lat2"], station["lon2"], station["azi2"] + angle, distance
        )
        return [p["lon2"], p["lat2"]]

    width = RADIUS_M + 2
    return [
        [offset(a, -90, width), offset(b, -90, width), offset(b, 90, width), offset(a, 90, width)]
        for a, b in zip(stations, stations[1:], strict=False)
    ]


def _sector_region(turn: dict[str, Any]) -> list[list[float]]:
    lon, lat = turn["center"]
    count = math.ceil(abs(turn["angle"]) / 5)
    radius = (RADIUS_M + 2) / math.cos(math.radians(abs(turn["angle"]) / count / 2))
    arc = [Geodesic.WGS84.Direct(lat, lon, turn["bearing"] + turn["angle"] * i / count,
                                radius) for i in range(count + 1)]
    return [[lon, lat]] + [[point["lon2"], point["lat2"]] for point in arc]


def _item_regions(item: dict[str, Any]) -> list[list[list[float]]]:
    if not item["geometry_valid"]:
        return []
    strips = _regions(item["coordinates"], item["leg_coordinates"])
    return strips + [_sector_region(turn) for turn in item["turns"]] if strips else []


def _sector_contains(turn: dict[str, Any], point: list[float]) -> bool:
    lon, lat = turn["center"]
    inverse = Geodesic.WGS84.Inverse(lat, lon, point[1], point[0])
    direction = 1 if turn["angle"] > 0 else -1
    angle = ((inverse["azi1"] - turn["bearing"]) * direction) % 360
    return bool(inverse["s12"] <= RADIUS_M + 1e-5 and (
        inverse["s12"] <= 1e-5 or angle <= abs(turn["angle"]) + 1e-8 or angle >= 360 - 1e-8
    ))


def contains_point(coordinates: list[list[float]], point: list[float]) -> bool:
    """Closed 3 NM geodesic strip, bounded by both endpoint normal planes."""
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
    terminal = Geodesic.WGS84.Inverse(lat2, lon2, lat, lon)
    if terminal["s12"] > 1e-5 and math.cos(
        math.radians(terminal["azi1"] - inverse["azi2"])
    ) > 1e-10:
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
        not (t.complete or t.evaluated)
        or t.required <= 0
        or t.valid <= 0
        or t.valid + t.missing != t.required
        or (t.complete and t.missing > 0)
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
    if not isinstance(raw, dict) or raw.get("policy") not in (POLICY, LEGACY_POLICY):
        return {}
    records = {}
    stored = raw.get("records")
    if not isinstance(stored, dict):
        return {}
    legacy_keys = legacy_interval_keys(project) if raw.get("policy") == LEGACY_POLICY else None
    for key, value in stored.items():
        try:
            record = SeaRecord.model_validate(value)
            if legacy_keys is not None:
                if key not in legacy_keys:
                    continue
                # Preserve old hand-written inputs, never adopt the old area evaluation.
                key = legacy_keys[key]
                record = SeaRecord(manual_ft=record.manual_ft)
            records[key] = record
        except (ValidationError, TypeError):
            pass  # Damaged optional SEA data must not stop flight calculations.
    return records


def legacy_interval_keys(project: Project) -> dict[str, str]:
    """Translate input-only v1 JSON manual values without trusting old terrain."""
    return {old["key"]: new["key"] for old, new in zip(
        _intervals(project, legacy=True), _intervals(project), strict=True
    )}


def sea_plan(project: Project, *, regions: bool = False) -> dict[str, Any]:
    intervals = _intervals(project)
    records = _records(project)
    for item in intervals:
        record = records.get(item["key"], SeaRecord()) if item["geometry_valid"] else SeaRecord()
        auto = automatic_sea(record) if _supported_inverse(item["coordinates"]) else None
        item.update(
            {
                "automatic_ft": auto,
                "reference": auto is not None and record.terrain.missing > 0,
                "manual_ft": record.manual_ft,
                "value_ft": auto,
                "status": "automatic" if auto is not None else "unknown",
                "warning": "unconfirmed" if auto is None else None,
                "terrain": record.terrain.model_dump(mode="json"),
            }
        )
        if regions:
            item["regions"] = _item_regions(item)
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
    if update.manual:
        raise ValueError("manual-sea-retired")
    plan = sea_plan(project)
    if project.id != update.project_id or plan["geometry_key"] != update.geometry_key:
        raise ValueError("stale-sea-geometry")
    records = _records(project)
    current = {item["key"]: item for item in plan["intervals"]}
    if set(update.terrain or {}) - current.keys() or set(update.manual or {}) - current.keys():
        raise ValueError("unknown-sea-interval")
    previous_keys = set(records)
    previous = project.metadata.get("sea", {})
    if isinstance(previous, dict) and previous.get("policy") == LEGACY_POLICY:
        previous_keys.clear()
    records = {key: records.get(key, SeaRecord()) for key in current}
    for key, terrain in (update.terrain or {}).items():
        records[key].terrain = terrain
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
        vertices = [point for region in _item_regions(current[key]) for point in region]
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
                and (contains_point(current[key]["coordinates"], coordinate)
                     or any(_sector_contains(turn, coordinate) for turn in current[key]["turns"]))
            ),
            None,
        )
    project.metadata["sea"] = {
        "policy": POLICY,
        "kml": kml,
        "records": {key: value.model_dump(mode="json") for key, value in records.items()},
    }
    # Keep historical diagnostics intact across the one-way evaluation-policy migration.
    if isinstance(previous, dict):
        legacy = previous if previous.get("policy") == LEGACY_POLICY else previous.get("legacy")
        if legacy is not None:
            project.metadata["sea"]["legacy"] = legacy


def prune_sea(project: Project) -> None:
    raw = project.metadata.get("sea")
    if not isinstance(raw, dict) or raw.get("policy") != POLICY:
        return
    keys = {item["key"] for item in _intervals(project)}
    raw["records"] = {
        key: value.model_dump(mode="json")
        for key, value in _records(project).items()
        if key in keys
    }
