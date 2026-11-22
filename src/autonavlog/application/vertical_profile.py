from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from itertools import groupby
from math import ceil, isfinite
from typing import Any

from autonavlog.domain.calculation import CalculationOutcome, SectionResult
from autonavlog.domain.enums import FlightPhase, VisualReferenceRole
from autonavlog.domain.planning import load_persisted_ui_state
from autonavlog.domain.project import Project
from autonavlog.nav.geodesy import geodesic_leg, point_along_leg


@dataclass(frozen=True)
class DescentProfile:
    """Vertical path for descent followed by level deceleration."""

    cruise_altitude_ft_msl: float
    target_altitude_ft_msl: float
    descent_rate_fpm: float
    vertical_duration_seconds: float
    deceleration_duration_seconds: float

    @property
    def planned_duration_seconds(self) -> float:
        return self.vertical_duration_seconds + self.deceleration_duration_seconds

    def altitude_at_elapsed(self, elapsed_seconds: float) -> float:
        """Return altitude after ``elapsed_seconds`` from EOC."""

        elapsed = min(max(float(elapsed_seconds), 0.0), self.vertical_duration_seconds)
        altitude = self.cruise_altitude_ft_msl - (
            elapsed / 60.0 * self.descent_rate_fpm
        )
        return max(self.target_altitude_ft_msl, altitude)


def descent_profile_from_metadata(
    metadata: Mapping[str, Any],
) -> DescentProfile | None:
    """Build a validated profile from calculation metadata."""

    cruise = _finite_number(metadata.get("cruise_altitude_ft_msl"))
    target = _finite_number(metadata.get("target_altitude_ft_msl"))
    rate = _finite_number(metadata.get("descent_rate_fpm"))
    vertical = _finite_number(metadata.get("vertical_descent_duration_seconds"))
    deceleration = _finite_number(metadata.get("deceleration_duration_seconds"))
    if None in {cruise, target, rate, vertical, deceleration}:
        return None
    assert cruise is not None
    assert target is not None
    assert rate is not None
    assert vertical is not None
    assert deceleration is not None
    if cruise < target or rate <= 0 or vertical < 0 or deceleration < 0:
        return None
    expected_vertical = (cruise - target) / rate * 60.0
    if abs(expected_vertical - vertical) > 1e-6:
        return None
    return DescentProfile(
        cruise_altitude_ft_msl=cruise,
        target_altitude_ft_msl=target,
        descent_rate_fpm=rate,
        vertical_duration_seconds=vertical,
        deceleration_duration_seconds=deceleration,
    )


def _finite_number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _descent_for_drawing(
    profile: DescentProfile, metadata: Mapping[str, Any], duration: float, start_distance: float,
) -> DescentProfile:
    """Absorb a recorded EOC snap only; never repair an altitude discontinuity.

    NAV LOG keeps its selected rate and distance/GS clock. Drawing may use a
    slightly different rate for at most 30 seconds of attributable snap error,
    retaining the one level-deceleration minute. Legacy results without this
    provenance do not acquire a guessed correction.
    """
    snap = metadata.get("eoc_snap")
    if snap is not None:
        if not isinstance(snap, Mapping):
            raise ValueError("Invalid saved EOC snap")
        original = _number(snap.get("original_distance_nm"))
        snapped = _number(snap.get("snapped_distance_nm"))
        adjustment = _number(snap.get("duration_adjustment_seconds"))
        if (
            original < 0 or snapped < 0
            or abs(snapped - start_distance) > 1e-6
            or not 0 < abs(original - snapped) < 0.5
            or (original - snapped) * adjustment <= 0
            or abs(adjustment) > 30.0 + 1e-6
            or abs(duration - profile.planned_duration_seconds - adjustment) > 1e-6
            or profile.deceleration_duration_seconds != 60.0
        ):
            raise ValueError("Unsupported saved EOC snap adjustment")
        vertical_seconds = duration - profile.deceleration_duration_seconds
        if vertical_seconds < 0 or (
            vertical_seconds == 0 and profile.vertical_duration_seconds > 0
        ):
            raise ValueError("Incomplete saved descent after EOC snap")
        if profile.vertical_duration_seconds > 0:
            return replace(
                profile,
                vertical_duration_seconds=vertical_seconds,
                descent_rate_fpm=(
                    (profile.cruise_altitude_ft_msl - profile.target_altitude_ft_msl)
                    / vertical_seconds * 60.0
                ),
            )
    # An unexplained surplus would silently extend the saved level/deceleration
    # interval, just as a deficit would truncate it. Only the snap above may
    # change the drawing clock; RJFM uses its saved operational zone times.
    if abs(duration - profile.planned_duration_seconds) > 1e-6:
        raise ValueError("Missing or incomplete saved descent profile")
    return profile


@dataclass(frozen=True)
class ProfilePoint:
    latitude_deg: float
    longitude_deg: float
    altitude_ft_msl: float
    elapsed_seconds: float
    distance_nm: float


@dataclass(frozen=True)
class ProfileSegment:
    section_id: str
    sequence: int
    phase: str
    points: tuple[ProfilePoint, ...]


@dataclass(frozen=True)
class ProfileMarker:
    name: str
    kind: str
    point: ProfilePoint
    # Check Points are ground references; their profile point is the saved abeam.
    reference_latitude_deg: float | None = None
    reference_longitude_deg: float | None = None


@dataclass(frozen=True)
class VerticalProfile:
    project_name: str
    departure_time: str
    segments: tuple[ProfileSegment, ...]
    markers: tuple[ProfileMarker, ...]


def _number(value: object) -> float:
    number = _finite_number(value)
    if number is None:
        raise ValueError("Incomplete vertical profile")
    return number


def _group_key(zone: SectionResult) -> tuple[FlightPhase, str]:
    # CP/physical-leg splits must not restart climb/descent or a Leg altitude ramp.
    return zone.phase, (
        "" if zone.phase in {
            FlightPhase.CLIMB, FlightPhase.DESCENT, FlightPhase.VISUAL_ARRIVAL,
        }
        else str(zone.section_id)
    )


def project_vertical_profile(project: Project, outcome: CalculationOutcome) -> VerticalProfile:
    """Project calculation-time inputs/results, never a working Project or live data.

    Shared by KML and the future time/altitude chart. Times, distances, phase
    boundaries and geometry come from non-overlapping calculation zones. Initial
    climb and EOC descent retain their saved timing, with a bounded drawing
    adjustment for recorded EOC snaps. Enroute altitude changes
    start at the Leg's origin at 900 fpm up / 500 fpm down, then level off; these
    are display rates, not new performance calculations. Visual arrival joins
    the VREP altitude to the saved destination elevation linearly by distance.
    No performance solver runs.
    Missing legacy data raises ValueError instead of inventing a flight path.
    """
    if project.id != outcome.project_id or not outcome.sections or not outcome.converged:
        raise ValueError("No completed vertical profile")
    zones = outcome.sections
    nodes = {node.id: node for node in project.route_nodes}
    first = zones[0]
    altitude = _number(first.planned_altitude_ft_msl.adopted())
    if first.phase == FlightPhase.CLIMB:
        snapshot = load_persisted_ui_state(project.metadata.get("ui_state")).reference_data_snapshot
        if snapshot is None:
            raise ValueError("Missing calculation-time departure elevation")
        altitude = float(snapshot.departure_airport.elevation_ft_msl)

    segments: list[ProfileSegment] = []
    markers: list[ProfileMarker] = []
    elapsed = distance = 0.0
    groups = [list(group) for _, group in groupby(zones, _group_key)]
    for group in groups:
        phase = group[0].phase
        start_time, start_altitude = elapsed, altitude
        start_distance = distance
        end_time = _number(group[-1].cumulative_ete_seconds.adopted())
        duration = end_time - start_time
        if duration <= 0:
            raise ValueError("Non-positive profile duration")
        descent = None
        saved_descent = None
        transition_seconds = duration
        target = _number(group[-1].planned_altitude_ft_msl.adopted())
        if phase == FlightPhase.CLIMB:
            # The first CLIMB input owns the one climb plan, even across Legs.
            target = _number(group[0].planned_altitude_ft_msl.adopted())
        elif phase == FlightPhase.DESCENT:
            saved_descent = descent_profile_from_metadata(group[0].performance_metadata)
            if saved_descent is None:
                raise ValueError("Missing or incomplete saved descent profile")
            descent = _descent_for_drawing(
                saved_descent, group[0].performance_metadata, duration, start_distance,
            )
            start_altitude = descent.cruise_altitude_ft_msl
            target = descent.target_altitude_ft_msl
            if segments and abs(altitude - start_altitude) > 1e-6:
                raise ValueError("Discontinuous saved descent profile")
        elif phase == FlightPhase.CRUISE:
            rate_fpm = 900 if target > start_altitude else 500
            transition_seconds = abs(target - start_altitude) / rate_fpm * 60
        elif phase == FlightPhase.VISUAL_ARRIVAL:
            snapshot = load_persisted_ui_state(
                project.metadata.get("ui_state"),
            ).reference_data_snapshot
            if (snapshot is None
                    or snapshot.destination_airport.id != project.destination_airport_id):
                raise ValueError("Missing calculation-time destination elevation")
            target = _number(snapshot.destination_airport.elevation_ft_msl)
            arrival_distance = _number(group[-1].cumulative_distance_nm.adopted()) - start_distance
            if arrival_distance <= 0:
                raise ValueError("Non-positive visual arrival distance")

        level_time = None
        if descent is not None:
            level_time = start_time + descent.vertical_duration_seconds
        elif phase == FlightPhase.CRUISE and transition_seconds > 0:
            level_time = start_time + transition_seconds

        for zone in group:
            zone_end_time = _number(zone.cumulative_ete_seconds.adopted())
            zone_end_distance = _number(zone.cumulative_distance_nm.adopted())
            seconds, length = zone_end_time - elapsed, zone_end_distance - distance
            if (seconds <= 0 or length < 0
                    or abs(seconds - _number(zone.zone_ete_seconds.adopted())) > 1e-6
                    or abs(length - _number(zone.zone_distance_nm.adopted())) > 1e-6):
                raise ValueError("Inconsistent calculation zone totals")
            if saved_descent != (
                descent_profile_from_metadata(zone.performance_metadata)
                if phase == FlightPhase.DESCENT else None
            ):
                raise ValueError("Inconsistent descent metadata")
            if phase == FlightPhase.DESCENT and (
                zone.performance_metadata.get("eoc_snap")
                != group[0].performance_metadata.get("eoc_snap")
            ):
                raise ValueError("Inconsistent saved EOC snap")
            start_lat, start_lon = _number(zone.from_latitude_deg), _number(zone.from_longitude_deg)
            end_lat, end_lon = _number(zone.to_latitude_deg), _number(zone.to_longitude_deg)
            geometry = geodesic_leg(start_lat, start_lon, end_lat, end_lon)
            # Absolute KML lines are chords. Sample the shared geodesic so long
            # legs do not cut beneath the globe; do not alter adopted distance.
            steps = max(1, ceil(geometry.distance_nm))
            fractions = {index / steps for index in range(steps + 1)}
            if level_time is not None and elapsed < level_time < zone_end_time:
                fractions.add((level_time - elapsed) / seconds)
            points: list[ProfilePoint] = []
            for fraction in sorted(fractions):
                time = elapsed + seconds * fraction
                lat, lon = (
                    (start_lat, start_lon) if fraction == 0 else
                    (end_lat, end_lon) if fraction == 1 else
                    point_along_leg(start_lat, start_lon, geometry.initial_true_course_deg,
                                    geometry.distance_nm * fraction)
                )
                height = (
                    start_altitude + (target - start_altitude)
                    * (distance + length * fraction - start_distance) / arrival_distance
                    if phase == FlightPhase.VISUAL_ARRIVAL else
                    descent.altitude_at_elapsed(time - start_time) if descent is not None
                    else target if transition_seconds == 0
                    else start_altitude + (target - start_altitude)
                    * min((time - start_time) / transition_seconds, 1.0)
                )
                point = ProfilePoint(lat, lon, height, time, distance + length * fraction)
                points.append(point)
                if level_time is not None and abs(time - level_time) < 1e-6:
                    if not any(m.kind == "LEVEL_OFF" and m.point == point for m in markers):
                        markers.append(ProfileMarker("LEVEL OFF", "LEVEL_OFF", point))
            segments.append(ProfileSegment(str(zone.section_id), zone.sequence, phase.value,
                                           tuple(points)))
            for node_id, point in ((zone.from_node_id, points[0]), (zone.to_node_id, points[-1])):
                node = nodes.get(node_id) if node_id is not None else None
                if node is not None:
                    marker = ProfileMarker(node.name, node.role.value, point)
                    if marker not in markers:
                        markers.append(marker)
            elapsed, distance = zone_end_time, zone_end_distance
            altitude = points[-1].altitude_ft_msl

    # All named boundaries already occur in the calculation zones. In particular,
    # do not re-solve EOC/RCA or project Check Points against a changed route.
    endpoints = [point for segment in segments for point in (segment.points[0], segment.points[-1])]
    for boundary in outcome.derived_points:
        point = _at_distance(endpoints, boundary.along_route_distance_nm)
        markers.append(ProfileMarker(boundary.type.value, boundary.type.value, point))
    references = {item.id: item for item in project.visual_references
                  if item.role == VisualReferenceRole.CHECK_POINT}
    for projection in outcome.check_point_projections:
        reference = references.get(projection.checkpoint_id)
        if reference is None:
            raise ValueError("Missing calculation-time Check Point")
        point = _at_distance(endpoints, projection.cumulative_distance_nm)
        markers.append(ProfileMarker(reference.name, "CHECK_POINT", point,
                                     reference.latitude_deg, reference.longitude_deg))
    return VerticalProfile(project.name, project.planned_departure_time_jst.isoformat(),
                           tuple(segments), tuple(markers))


def _at_distance(points: list[ProfilePoint], distance: float) -> ProfilePoint:
    for point in points:
        if abs(point.distance_nm - distance) < 1e-6:
            return point
    raise ValueError("Saved boundary is missing from calculation zones")
