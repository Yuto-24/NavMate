from __future__ import annotations

from uuid import uuid4

import pytest

from autonavlog.application.vertical_profile import (
    DescentProfile,
    descent_profile_from_metadata,
    project_vertical_profile,
)
from autonavlog.domain.calculation import CalculationOutcome, SectionResult
from autonavlog.domain.enums import FlightPhase
from autonavlog.domain.planning import (
    AirportSelection,
    CheckPointProjection,
    PatternAltitudeValidationStatus,
    PersistedUiState,
    ReferenceDataSnapshot,
)
from autonavlog.domain.project import VisualReference
from autonavlog.domain.values import AdoptedValue


def _value(number):
    return AdoptedValue(automatic_value=number, automatic_status="AUTO", adopted_source="AUTOMATIC")


def _zone(index, phase, start, end, seconds, cumulative,
          metadata=None, section_id=None, altitude=5500):
    # Only the projection's input fields; no calculation service in display tests.
    return SectionResult.model_construct(
        section_id=section_id or uuid4(), sequence=index, phase=FlightPhase(phase),
        from_latitude_deg=32.0, from_longitude_deg=130 + start / 100,
        to_latitude_deg=32.0, to_longitude_deg=130 + end / 100,
        planned_altitude_ft_msl=_value(altitude), from_node_id=None, to_node_id=None,
        zone_ete_seconds=_value(seconds), cumulative_ete_seconds=_value(cumulative),
        zone_distance_nm=_value(end-start), cumulative_distance_nm=_value(end),
        performance_metadata=metadata or {},
    )


@pytest.mark.parametrize("deceleration", [0, 60])
def test_shared_projection_preserves_descent_clock_across_splits(project, deceleration):
    metadata = {"cruise_altitude_ft_msl": 5500, "target_altitude_ft_msl": 1500,
                "descent_rate_fpm": 500, "vertical_descent_duration_seconds": 480,
                "deceleration_duration_seconds": deceleration}
    zones = [_zone(0, "CRUISE", 0, 10, 100, 100),
             _zone(1, "DESCENT", 10, 20, 240, 340, metadata),
             _zone(2, "DESCENT", 20, 30, 240 + deceleration, 580 + deceleration, metadata)]
    outcome = CalculationOutcome.model_construct(
        project_id=project.id, sections=zones, converged=True,
    )
    profile = project_vertical_profile(project, outcome)
    assert profile.segments[1].points[-1].altitude_ft_msl == 3500
    level = next(marker.point for marker in profile.markers if marker.kind == "LEVEL_OFF")
    assert level.altitude_ft_msl == 1500
    assert level.elapsed_seconds == 580
    assert profile.segments[-1].points[-1].elapsed_seconds - level.elapsed_seconds == deceleration
    assert profile.segments[-1].points[-1].distance_nm == 30
    assert profile.segments[-1].points[-1].altitude_ft_msl == 1500
    # No metadata fallback to the working Project's descent rate.
    zones[-1].performance_metadata = {}
    with pytest.raises(ValueError, match="metadata"):
        project_vertical_profile(project, outcome)


@pytest.mark.parametrize("adjustment", [-30.0, -12.0, 12.0, 30.0])
def test_eoc_snap_drawing_adjusts_only_the_rate_and_retains_level_minute(project, adjustment):
    metadata = {"cruise_altitude_ft_msl": 5500, "target_altitude_ft_msl": 1500,
                "descent_rate_fpm": 500, "vertical_descent_duration_seconds": 480,
                "deceleration_duration_seconds": 60,
                "eoc_snap": {"original_distance_nm": 10 + (0.4 if adjustment > 0 else -0.4),
                             "snapped_distance_nm": 10,
                             "duration_adjustment_seconds": adjustment}}
    zones = [_zone(0, "CRUISE", 0, 10, 100, 100),
             _zone(1, "DESCENT", 10, 20, 240, 340, metadata),
             _zone(2, "DESCENT", 20, 30, 300 + adjustment, 640 + adjustment, metadata)]
    outcome = CalculationOutcome.model_construct(
        project_id=project.id, sections=zones, converged=True,
    )
    original = outcome.model_dump(mode="json")
    profile = project_vertical_profile(project, outcome)
    level = next(marker.point for marker in profile.markers if marker.kind == "LEVEL_OFF")
    assert level.altitude_ft_msl == pytest.approx(1500)
    assert level.elapsed_seconds == pytest.approx(580 + adjustment)
    assert profile.segments[-1].points[-1].elapsed_seconds - level.elapsed_seconds == 60
    expected_rate = 4000 / (480 + adjustment) * 60
    assert profile.segments[1].points[-1].altitude_ft_msl == pytest.approx(
        5500 - expected_rate * 240 / 60,
    )
    assert outcome.model_dump(mode="json") == original
    # Even valid snap provenance cannot justify a jump at the EOC altitude.
    zones[0].planned_altitude_ft_msl = _value(6500)
    with pytest.raises(ValueError, match="Discontinuous"):
        project_vertical_profile(project, outcome)


@pytest.mark.parametrize("snap", [
    None,
    {"original_distance_nm": 9.6, "snapped_distance_nm": 10,
     "duration_adjustment_seconds": -30.001},
    {"original_distance_nm": 9.5, "snapped_distance_nm": 10,
     "duration_adjustment_seconds": -12},
    {"original_distance_nm": 10.4, "snapped_distance_nm": 10,
     "duration_adjustment_seconds": -12},
    {"original_distance_nm": 9.6, "snapped_distance_nm": 10,
     "duration_adjustment_seconds": -11},
    {"original_distance_nm": 99.6, "snapped_distance_nm": 100,
     "duration_adjustment_seconds": -12},
])
def test_incomplete_descent_is_not_repaired_without_bounded_matching_snap(project, snap):
    metadata = {"cruise_altitude_ft_msl": 5500, "target_altitude_ft_msl": 1500,
                "descent_rate_fpm": 500, "vertical_descent_duration_seconds": 480,
                "deceleration_duration_seconds": 60}
    if snap is not None:
        metadata["eoc_snap"] = snap
    duration = (
        540 + snap["duration_adjustment_seconds"]
        if snap is not None and abs(snap["duration_adjustment_seconds"]) > 30
        else 528
    )
    zones = [_zone(0, "CRUISE", 0, 10, 100, 100),
             _zone(1, "DESCENT", 10, 30, duration, 100 + duration, metadata)]
    outcome = CalculationOutcome.model_construct(
        project_id=project.id, sections=zones, converged=True,
    )
    with pytest.raises(ValueError):
        project_vertical_profile(project, outcome)


@pytest.mark.parametrize("start,target,rate", [(5500, 7500, 900), (7500, 5500, 500)])
def test_enroute_transition_starts_after_turn_and_levels_off_across_cp_splits(
    project, start, target, rate,
):
    project.descent_rate_fpm = 1000  # Enroute drawing still uses 500 fpm down.
    section_id = uuid4()
    zones = [_zone(0, "CRUISE", 0, 10, 100, 100, altitude=start),
             _zone(1, "CRUISE", 10, 15, 50, 150, section_id=section_id, altitude=target),
             _zone(2, "CRUISE", 15, 20, 250, 400, section_id=section_id, altitude=target)]
    reference = VisualReference(name="CP<&", latitude_deg=32.1, longitude_deg=130.15,
                                role="CHECK_POINT", linked_section_id=section_id)
    project.visual_references.append(reference)
    projection = CheckPointProjection(
        checkpoint_id=reference.id, section_id=section_id,
        abeam_latitude_deg=32, abeam_longitude_deg=130.15, along_track_fraction=0.5,
        along_section_distance_nm=5, cumulative_distance_nm=15, cross_track_distance_nm=6,
    )
    outcome = CalculationOutcome.model_construct(
        project_id=project.id, sections=zones, converged=True,
        check_point_projections=[projection],
    )
    profile = project_vertical_profile(project, outcome)
    sign = 1 if target > start else -1
    at_cp = start + sign * rate * 50 / 60
    assert all(p.altitude_ft_msl == start for p in profile.segments[0].points)
    assert profile.segments[1].points[0].altitude_ft_msl == start
    assert profile.segments[1].points[-1].altitude_ft_msl == pytest.approx(at_cp)
    assert profile.segments[2].points[0].altitude_ft_msl == pytest.approx(at_cp)
    assert profile.segments[2].points[-1].altitude_ft_msl == target
    level = next(m.point for m in profile.markers if m.kind == "LEVEL_OFF")
    assert level.elapsed_seconds == pytest.approx(100 + abs(target - start) / rate * 60)
    assert level.altitude_ft_msl == target
    assert level in profile.segments[2].points
    assert all(p.altitude_ft_msl == target for p in profile.segments[2].points
               if p.elapsed_seconds >= level.elapsed_seconds)
    marker = next(marker for marker in profile.markers if marker.kind == "CHECK_POINT")
    assert marker.name == "CP<&"
    assert marker.point.elapsed_seconds == 150
    assert marker.point.altitude_ft_msl == pytest.approx(at_cp)
    assert marker.point.latitude_deg == 32
    assert marker.reference_latitude_deg == 32.1
    zones[-1].from_latitude_deg = None
    with pytest.raises(ValueError, match="Incomplete"):
        project_vertical_profile(project, outcome)


def test_descent_profile_levels_off_before_one_minute_deceleration() -> None:
    profile = DescentProfile(
        cruise_altitude_ft_msl=5_500,
        target_altitude_ft_msl=1_500,
        descent_rate_fpm=500,
        vertical_duration_seconds=480,
        deceleration_duration_seconds=60,
    )

    assert profile.planned_duration_seconds == 540
    assert profile.altitude_at_elapsed(0) == 5_500
    assert profile.altitude_at_elapsed(240) == 3_500
    assert profile.altitude_at_elapsed(480) == 1_500
    assert profile.altitude_at_elapsed(540) == 1_500


def test_short_enroute_leg_does_not_accelerate_to_reach_target(project):
    zones = [_zone(0, "CRUISE", 0, 10, 100, 100, altitude=5500),
             _zone(1, "CRUISE", 10, 12, 60, 160, altitude=7500),
             _zone(2, "CRUISE", 12, 20, 240, 400, altitude=7500)]
    outcome = CalculationOutcome.model_construct(
        project_id=project.id, sections=zones, converged=True,
    )
    profile = project_vertical_profile(project, outcome)
    assert profile.segments[1].points[-1].altitude_ft_msl == 6400
    assert profile.segments[2].points[0].altitude_ft_msl == 6400
    level = next(m.point for m in profile.markers if m.kind == "LEVEL_OFF")
    assert level.elapsed_seconds == pytest.approx(100 + 2000 / 900 * 60)
    assert level.altitude_ft_msl == 7500


def test_visual_arrival_joins_vrep_to_saved_field_elevation_by_distance(project):
    destination = AirportSelection(
        id=project.destination_airport_id, icao=project.destination_airport_id,
        name="Destination", latitude_deg=32, longitude_deg=130.2,
        elevation_ft_msl=42, pattern_altitude_ft_msl=1000,
        pattern_altitude_source="fixture", pattern_altitude_source_revision="fixture-v1",
        pattern_altitude_validation_status=PatternAltitudeValidationStatus.VERIFIED,
        source="fixture", source_revision="fixture-v1",
    )
    state = PersistedUiState(reference_data_snapshot=ReferenceDataSnapshot(
        departure_airport=destination, destination_airport=destination,
    ))
    project.metadata["ui_state"] = state.model_dump(mode="json")
    section_id = uuid4()
    zones = [_zone(0, "CRUISE", 0, 10, 100, 100, altitude=1500),
             _zone(1, "VISUAL_ARRIVAL", 10, 15, 60, 160,
                   section_id=section_id, altitude=1500),
             _zone(2, "VISUAL_ARRIVAL", 15, 20, 180, 340,
                   section_id=section_id, altitude=1500)]
    zones[1].from_node_id = project.route_nodes[-2].id
    zones[-1].to_node_id = project.route_nodes[-1].id
    outcome = CalculationOutcome.model_construct(
        project_id=project.id, sections=zones, converged=True,
    )
    original = outcome.model_dump()
    profile = project_vertical_profile(project, outcome)
    assert profile.segments[1].points[0].altitude_ft_msl == 1500
    # Half the distance but only one quarter of the arrival time.
    assert profile.segments[1].points[-1].altitude_ft_msl == pytest.approx(771)
    assert profile.segments[2].points[0] == profile.segments[1].points[-1]
    for segment in profile.segments[1:]:
        assert segment.phase == "VISUAL_ARRIVAL"
        for point in segment.points:
            assert point.altitude_ft_msl == pytest.approx(
                1500 + (42 - 1500) * (point.distance_nm - 10) / 10
            )
    final = profile.segments[-1].points[-1]
    assert final.altitude_ft_msl == 42
    assert (final.latitude_deg, final.longitude_deg) == (32, 130.2)
    assert final.elapsed_seconds == 340
    assert next(m.point for m in profile.markers
                if m.name == project.route_nodes[-1].name) == final
    assert outcome.model_dump() == original
    project.metadata["ui_state"]["reference_data_snapshot"]["destination_airport"]["id"] = "OTHER"
    with pytest.raises(ValueError, match="destination elevation"):
        project_vertical_profile(project, outcome)
    project.metadata.pop("ui_state")
    with pytest.raises(ValueError, match="ui_state"):
        project_vertical_profile(project, outcome)


def test_inconsistent_eoc_altitude_does_not_retarget_the_preceding_leg(project):
    metadata = {"cruise_altitude_ft_msl": 7500, "target_altitude_ft_msl": 1500,
                "descent_rate_fpm": 500, "vertical_descent_duration_seconds": 720,
                "deceleration_duration_seconds": 60}
    zones = [_zone(0, "CRUISE", 0, 10, 300, 300, altitude=5500),
             _zone(1, "DESCENT", 10, 30, 780, 1080, metadata)]
    outcome = CalculationOutcome.model_construct(
        project_id=project.id, sections=zones, converged=True,
    )
    with pytest.raises(ValueError, match="Discontinuous"):
        project_vertical_profile(project, outcome)


def test_descent_profile_is_built_only_from_consistent_metadata() -> None:
    metadata = {
        "cruise_altitude_ft_msl": 5_500,
        "target_altitude_ft_msl": 1_500,
        "descent_rate_fpm": 500,
        "vertical_descent_duration_seconds": 480,
        "deceleration_duration_seconds": 60,
    }

    profile = descent_profile_from_metadata(metadata)
    assert profile is not None
    assert profile.altitude_at_elapsed(60) == pytest.approx(5_000)
    assert (
        descent_profile_from_metadata(
            metadata | {"vertical_descent_duration_seconds": 60}
        )
        is None
    )
