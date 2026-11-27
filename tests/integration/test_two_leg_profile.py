"""A physical turn is not required at each climb/cruise/descent boundary."""

import pytest

from autonavlog.application.calculation_service import CalculationService
from autonavlog.application.vertical_profile import project_vertical_profile
from autonavlog.domain.enums import AdoptedSource, FlightPhase, RouteNodeRole
from autonavlog.domain.planning import (
    AirportSelection,
    ArrivalAltitudeMode,
    ArrivalPlan,
    PatternAltitudeValidationStatus,
    PersistedUiState,
    ReferenceDataSnapshot,
)
from autonavlog.domain.project import ManualWind
from autonavlog.weather.fake_provider import FakeWeatherProvider


@pytest.fixture
def two_leg_project(project, airports):
    project.route_nodes[1].role = RouteNodeRole.VISUAL_REPORTING_POINT
    project.route_nodes[0].manual_distance_nm = 60
    project.sections[1].phase = FlightPhase.VISUAL_ARRIVAL
    project.sections[1].planned_altitude_ft_msl = 1500
    project.route_nodes[1].manual_distance_nm = 5
    selections = [
        AirportSelection(
            **airports.get(airport_id).model_dump(),
            pattern_altitude_source="fixture",
            pattern_altitude_source_revision="fixture-v1",
            pattern_altitude_validation_status=PatternAltitudeValidationStatus.VERIFIED,
        )
        for airport_id in (project.departure_airport_id, project.destination_airport_id)
    ]
    project.metadata["ui_state"] = PersistedUiState(
        arrival_plan=ArrivalPlan(
            visual_reporting_point_node_id=project.route_nodes[1].id,
            selected_pattern_altitude_ft_msl=1000,
            selected_pattern_altitude_source=AdoptedSource.MANUAL,
            altitude_mode=ArrivalAltitudeMode.MANUAL_NON_STANDARD_ENTRY,
            manual_vrep_altitude_ft_msl=1500,
            manual_override_reason="Two-leg regression",
        ),
        reference_data_snapshot=ReferenceDataSnapshot(
            departure_airport=selections[0], destination_airport=selections[1],
        ),
    ).model_dump(mode="json")
    return project


@pytest.mark.parametrize("rate", [500, 1000])
def test_two_leg_route_has_continuous_climb_cruise_descent(
    airports, performance_repository, two_leg_project, rate,
):
    two_leg_project.descent_rate_fpm = rate
    outcome = CalculationService(airports, performance_repository).calculate(
        two_leg_project, FakeWeatherProvider(),
    )
    assert not outcome.blockers
    assert [row.phase for row in outcome.sections] == [
        FlightPhase.CLIMB, FlightPhase.CRUISE, FlightPhase.DESCENT, FlightPhase.VISUAL_ARRIVAL,
    ]
    climb, cruise, descent, visual = outcome.sections
    assert [point.type.value for point in outcome.derived_points] == ["RCA", "EOC"]
    assert all(
        row.performance_metadata["phase_segment"]["source_section_id"]
        == str(two_leg_project.sections[0].id)
        for row in (climb, cruise, descent)
    )
    assert descent.cas_kt.adopted() == pytest.approx(cruise.cas_kt.adopted())
    assert descent.performance_metadata["target_altitude_ft_msl"] == 1500
    assert descent.zone_ete_seconds.adopted() == pytest.approx(3500 / rate * 60 + 60)
    assert descent.section_fuel_gal.adopted() == pytest.approx(
        descent.zone_ete_seconds.adopted() / 3600 * 12,
    )
    assert descent.cumulative_distance_nm.adopted() == pytest.approx(60)
    assert visual.cumulative_distance_nm.adopted() == pytest.approx(65)
    assert len(two_leg_project.route_nodes) == 3
    assert len(two_leg_project.sections) == 2
    profile = project_vertical_profile(two_leg_project, outcome)
    for before, after in zip(profile.segments, profile.segments[1:], strict=False):
        assert before.points[-1] == after.points[0]
    descending = next(segment for segment in profile.segments if segment.phase == "DESCENT")
    assert descending.points[0].altitude_ft_msl == 5000
    assert descending.points[-1].altitude_ft_msl == 1500
    level_off = next(point for point in descending.points if point.altitude_ft_msl == 1500)
    assert descending.points[-1].elapsed_seconds - level_off.elapsed_seconds == pytest.approx(60)


@pytest.mark.parametrize("distance,altitude", [(5, 5000), (30, 5000), (60, 1000)])
def test_two_leg_infeasible_route_is_blocked(
    airports, performance_repository, two_leg_project, distance, altitude,
):
    two_leg_project.route_nodes[0].manual_distance_nm = distance
    two_leg_project.sections[0].planned_altitude_ft_msl = altitude
    outcome = CalculationService(airports, performance_repository).calculate(
        two_leg_project, FakeWeatherProvider(),
    )
    assert outcome.blockers
    assert any(issue.code in {
        "RCA_OUTSIDE_ROUTE", "DESCENT_CRUISE_CAS_SOURCE_UNAVAILABLE",
        "DESCENT_ALTITUDE_CONSTRAINT_INFEASIBLE", "PHASE_SEGMENTATION_FAILED",
    } for issue in outcome.blockers)


def test_two_leg_uses_phase_weather_and_cruise_cas(
    airports, performance_repository, two_leg_project,
):
    section = two_leg_project.sections[0]
    section.manual_tas_kt_by_phase = {FlightPhase.CRUISE: 140}
    section.manual_wind_by_phase = {
        FlightPhase.CLIMB: ManualWind(direction_deg_from=360, speed_kt=10),
        FlightPhase.CRUISE: ManualWind(direction_deg_from=90, speed_kt=15),
        FlightPhase.DESCENT: ManualWind(direction_deg_from=180, speed_kt=20),
    }
    section.manual_temperature_c_by_phase = {
        FlightPhase.CLIMB: 10, FlightPhase.CRUISE: 5, FlightPhase.DESCENT: 15,
    }
    provider = FakeWeatherProvider()
    outcome = CalculationService(airports, performance_repository).calculate(
        two_leg_project, provider,
    )
    assert not outcome.blockers
    climb, cruise, descent, _ = outcome.sections
    assert climb.cas_kt.adopted() == 111
    assert cruise.tas_kt.adopted() == 140
    assert descent.cas_kt.adopted() == pytest.approx(cruise.cas_kt.adopted())
    for row, speed, temperature in ((climb, 10, 10), (cruise, 15, 5), (descent, 20, 15)):
        assert row.wind_speed_kt.adopted() == speed
        assert row.temperature_c.adopted() == temperature
    requests = {request.metadata.get("phase"): request
                for request in provider.query_history[-1][1]
                if request.request_id.startswith(f"section:{section.id}:")}
    assert requests["CLIMB"].altitude_ft_msl == 2510
    assert requests["CRUISE"].altitude_ft_msl == 5000
    assert requests["DESCENT"].altitude_ft_msl == 3250
