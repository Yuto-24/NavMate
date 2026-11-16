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
from autonavlog.domain.planning import CheckPointProjection
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


def test_leg_ramp_is_not_restarted_at_check_point_splits(project):
    section_id = uuid4()
    zones = [_zone(0, "CRUISE", 0, 10, 100, 100, altitude=5500),
             _zone(1, "CRUISE", 10, 15, 50, 150, section_id=section_id, altitude=7500),
             _zone(2, "CRUISE", 15, 20, 150, 300, section_id=section_id, altitude=7500)]
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
    assert profile.segments[1].points[-1].altitude_ft_msl == 6000
    assert profile.segments[2].points[0].altitude_ft_msl == 6000
    assert profile.segments[2].points[-1].altitude_ft_msl == 7500
    marker = next(marker for marker in profile.markers if marker.kind == "CHECK_POINT")
    assert marker.name == "CP<&"
    assert marker.point.elapsed_seconds == 150
    assert marker.point.altitude_ft_msl == 6000
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
