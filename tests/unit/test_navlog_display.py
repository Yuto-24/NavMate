from types import SimpleNamespace
from uuid import uuid4

import pytest

from autonavlog.application.navlog_display import (
    NavLogPhysicalLeg,
    _allocate_raw_largest_remainder_ticks,
    _display_distance_cells,
    _display_fuel_combined,
    build_navlog_display_rows,
    build_navlog_summary,
)
from autonavlog.domain.calculation import NavLogDisplayRow, SectionResult
from autonavlog.domain.enums import AdoptedSource, DisplayCellState, FlightPhase, ValueState
from autonavlog.domain.values import AdoptedValue
from autonavlog.nav.wind_triangle import solve_wind_triangle


def _automatic(value: float) -> AdoptedValue[float]:
    return AdoptedValue[float](
        automatic_value=value,
        automatic_status=ValueState.AUTO,
        adopted_source=AdoptedSource.AUTOMATIC,
    )


def test_fuel_parent_sums_rounded_children_and_subtracts_display_remaining() -> None:
    values = [_automatic(0.14), _automatic(0.14)]
    exact_remaining = _automatic(49.72)

    cell, display_remaining_tenths = _display_fuel_combined(
        values,
        exact_remaining,
        prior_display_remaining_tenths=500,
        fallback_reason="DISPLAY_FUEL_SUBTOTAL_UNAVAILABLE",
    )

    assert cell.state == DisplayCellState.DISPLAY_VALUE
    assert cell.text == "0.2 / 49.8"
    assert cell.effective_value == "0.28/49.72"
    assert display_remaining_tenths == 498
    assert [value.adopted() for value in values] == [0.14, 0.14]
    assert exact_remaining.adopted() == 49.72


def test_distance_children_allocate_the_rounded_parent_ticks_in_route_order() -> None:
    """A display total of 1.0 NM has two ticks, not three independently rounded zones."""
    zones = [SimpleNamespace(zone_distance_nm=_automatic(value)) for value in (0.3, 0.3, 0.4)]
    leg = NavLogPhysicalLeg(
        section_ids=(uuid4(),),
        phase=FlightPhase.CRUISE,
        start_name="FROM",
        end_name="TO",
        adopted_distance_nm=1.0,
    )

    parent, cumulative, children = _display_distance_cells(
        leg,
        zones,
        prior_display_cumulative=2.5,
    )

    assert parent.text == "1.0 / 3.5"
    assert cumulative == 3.5
    # The two equal fractional remainders use the earlier Zone as the tie-break.
    assert [cell.text for cell in children] == ["0.5", "0.0", "0.5"]
    assert [cell.effective_value for cell in children] == [0.3, 0.3, 0.4]
    assert all(cell.state == DisplayCellState.DISPLAY_VALUE for cell in children)


def test_distance_allocation_fails_closed_when_zone_distances_do_not_match_leg() -> None:
    zones = [SimpleNamespace(zone_distance_nm=_automatic(value)) for value in (0.3, 0.4)]
    leg = NavLogPhysicalLeg(
        section_ids=(uuid4(),),
        phase=FlightPhase.CRUISE,
        start_name="FROM",
        end_name="TO",
        adopted_distance_nm=1.0,
    )

    parent, cumulative, children = _display_distance_cells(
        leg,
        zones,
        prior_display_cumulative=0.0,
    )

    assert parent.state == DisplayCellState.UNAVAILABLE
    assert parent.reason_code == "DISPLAY_DISTANCE_ALLOCATION_UNAVAILABLE"
    assert cumulative is None
    assert all(cell.state == DisplayCellState.UNAVAILABLE for cell in children)


def test_rjfm_inbound_ete_keeps_raw_unit_largest_remainder_behavior() -> None:
    """ETE must not proportionally normalize the once-rounded profile total."""
    assert _allocate_raw_largest_remainder_ticks([0.25, 1.25], 2) == [1, 1]


def test_rjfm_inbound_ete_keeps_zero_duration_candidates() -> None:
    assert _allocate_raw_largest_remainder_ticks([0.0, 0.0], 0) == [0, 0]


def _summary_zone() -> SectionResult:
    """Only distance/time values are populated by each summary test."""
    return SectionResult(
        section_id=uuid4(),
        sequence=0,
        phase=FlightPhase.CLIMB,
        from_name="FROM",
        to_name="RCA",
        planned_altitude_ft_msl=_automatic_value(None),
        pressure_altitude_exact_ft=_automatic_value(None),
        pressure_altitude_planning_ft=_automatic_value(None),
        true_course_deg=_automatic_value(None),
        variation_deg_east=_automatic_value(None),
        magnetic_course_deg=_automatic_value(None),
        wind_direction_deg_from=_automatic_value(None),
        wind_speed_kt=_automatic_value(None),
        wca_deg=_automatic_value(None),
        magnetic_heading_deg=_automatic_value(None),
        temperature_c=_automatic_value(None),
        cas_kt=_automatic_value(None),
        tas_kt=_automatic_value(None),
        ground_speed_kt=_automatic_value(None),
        zone_distance_nm=_automatic_value(None),
        cumulative_distance_nm=_automatic_value(None),
        zone_ete_seconds=_automatic_value(None),
        cumulative_ete_seconds=_automatic_value(None),
        section_fuel_gal=_automatic_value(None),
        remaining_fuel_gal=_automatic_value(None),
    )


def _automatic_value(value: float | None) -> AdoptedValue[float]:
    return AdoptedValue(
        automatic_value=value,
        automatic_status=ValueState.AUTO if value is not None else ValueState.UNAVAILABLE,
        adopted_source=AdoptedSource.AUTOMATIC if value is not None else None,
    )


@pytest.mark.parametrize("temperature", [15.0, -5.0, None], ids=["equal", "different", "missing"])
def test_eoc_toat_boundary_resumes_inheritance_within_the_same_leg(airports, temperature):
    source = _summary_zone()
    # Missing values on both sides must also establish a visible boundary.
    cruise_temperature = None if temperature is None else 15.0
    zones = [
        source.model_copy(update={
            "sequence": index,
            "phase": phase,
            "from_name": start,
            "to_name": end,
            "temperature_c": _automatic_value(value),
            "zone_distance_nm": _automatic(1.0),
        })
        for index, (phase, start, end, value) in enumerate([
            (FlightPhase.CRUISE, "WP1", "CP: BEFORE", cruise_temperature),
            (FlightPhase.CRUISE, "CP: BEFORE", "EOC", cruise_temperature),
            (FlightPhase.DESCENT, "EOC", "CP: AFTER", temperature),
            (FlightPhase.DESCENT, "CP: AFTER", "WP2", temperature),
        ])
    ]
    rows = build_navlog_display_rows(
        [NavLogPhysicalLeg(
            section_ids=(source.section_id,),
            phase=FlightPhase.CRUISE,
            start_name="WP1",
            end_name="WP2",
            adopted_distance_nm=4.0,
        )],
        zones,
        airports.get("RJFM"),
        airports.get("RJFO"),
        None, None, None,
        total_usable_fuel_gal=90.0,
        run_up_included=False,
    )
    before, eoc, first_descent, later_descent = [
        row for row in rows if row.row_type == "CALCULATION_ZONE"
    ]
    for row in (before, eoc, later_descent):
        assert row.toat.state == DisplayCellState.INHERIT
        assert row.toat.text is None
    assert later_descent.toat.effective_value == temperature
    assert first_descent.toat.effective_value == temperature
    if temperature is None:
        assert first_descent.toat.state == DisplayCellState.UNAVAILABLE
        assert first_descent.toat.reason_code == "TEMPERATURE_UNAVAILABLE"
    else:
        assert first_descent.toat.state == DisplayCellState.DISPLAY_VALUE
        assert first_descent.toat.text == f"{temperature:.1f}"


def test_navlog_summary_uses_canonical_split_zones_and_hhmm_rounding() -> None:
    source = _summary_zone()
    first = source.model_copy(
        update={
            "sequence": 0,
            "zone_distance_nm": _automatic_value(1.2),
            "cumulative_distance_nm": _automatic_value(1.2),
            "zone_ete_seconds": _automatic_value(29.5 * 60),
            "cumulative_ete_seconds": _automatic_value(29.5 * 60),
        }
    )
    second = source.model_copy(
        update={
            "sequence": 1,
            "zone_distance_nm": _automatic_value(1.3),
            "cumulative_distance_nm": _automatic_value(2.5),
            "zone_ete_seconds": _automatic_value(30 * 60),
            "cumulative_ete_seconds": _automatic_value(59.5 * 60),
        }
    )
    summary = build_navlog_summary(
        [first, second],
        [
            NavLogPhysicalLeg(
                section_ids=(source.section_id,),
                phase=source.phase,
                start_name=source.from_name,
                end_name=source.to_name,
                adopted_distance_nm=2.5,
            )
        ],
    )

    assert summary.distance.text == "2.5"
    assert summary.time.text == "1:00"


def test_navlog_summary_keeps_distance_when_an_early_ete_is_unavailable() -> None:
    first = _summary_zone()
    unavailable_first = first.model_copy(
        update={
            "zone_distance_nm": _automatic_value(1.2),
            "zone_ete_seconds": _automatic_value(None),
        }
    )
    available_second = first.model_copy(
        update={
            "section_id": uuid4(),
            "sequence": 1,
            "zone_distance_nm": _automatic_value(2.0),
            "zone_ete_seconds": _automatic_value(60.0),
        }
    )
    summary = build_navlog_summary(
        [unavailable_first, available_second],
        [
            NavLogPhysicalLeg(
                section_ids=(first.section_id,),
                phase=first.phase,
                start_name=first.from_name,
                end_name=first.to_name,
                adopted_distance_nm=1.2,
            ),
            NavLogPhysicalLeg(
                section_ids=(available_second.section_id,),
                phase=available_second.phase,
                start_name=available_second.from_name,
                end_name=available_second.to_name,
                adopted_distance_nm=2.0,
            ),
        ],
    )

    assert summary.distance.text == "3.0"
    assert summary.time.text == "未取得"
    assert summary.time.reason_code == "SUMMARY_TIME_UNAVAILABLE"


@pytest.mark.parametrize("wind,missing", [(0, False), (20, False), (20, True)])
def test_cut_is_entry_parent_only_uses_adopted_values_and_preserves_zones(airports, wind, missing):
    from autonavlog.application.thirty_degree_cut import solve_thirty_degree_cut

    nodes = [uuid4() for _ in range(3)]
    section_ids = [uuid4(), uuid4()]
    zones = []
    for index, (course, variation) in enumerate([(0.0, -6.0), (90.0, -7.0)]):
        heading = solve_wind_triangle(course, 120, 270, wind).true_heading_deg
        for offset in range(2):
            zone = _summary_zone().model_copy(update={
                "section_id": section_ids[index], "sequence": index * 2 + offset,
                "phase": FlightPhase.CRUISE,
                "from_node_id": nodes[index] if offset == 0 else None,
                "to_node_id": nodes[index + 1] if offset == 1 else None,
                "true_course_deg": _automatic(course),
                "variation_deg_east": _automatic(variation),
                "magnetic_course_deg": _automatic((course + variation) % 360),
                "magnetic_heading_deg": _automatic((heading + variation) % 360),
                "tas_kt": _automatic(120),
                "wind_speed_kt": _automatic(wind),
                # CALM needs no direction, non-calm must have one.
                "wind_direction_deg_from": _automatic_value(None if wind == 0 or missing else 270),
                "zone_distance_nm": _automatic(5),
            })
            zones.append(zone)
    legs = [NavLogPhysicalLeg(
        section_ids=(section_ids[index],), phase=FlightPhase.CRUISE,
        start_name=str(index), end_name=str(index + 1),
        start_node_id=nodes[index], end_node_id=nodes[index + 1], adopted_distance_nm=10,
    ) for index in range(2)]
    original = [zone.model_dump() for zone in zones]
    rows = build_navlog_display_rows(
        legs, zones, airports.get("RJFM"), airports.get("RJFO"), None, None, None,
        total_usable_fuel_gal=90, run_up_included=False,
    )
    parents = [row for row in rows if row.row_type == "PHYSICAL_LEG_SUMMARY"]
    assert parents[0].thirty_degree_cut_seconds is None
    assert all(row.thirty_degree_cut_seconds is None for row in rows
               if row.row_type != "PHYSICAL_LEG_SUMMARY")
    if missing:
        assert parents[1].thirty_degree_cut_seconds is None
    else:
        expected = solve_thirty_degree_cut(
            inbound_course_deg=0,
            inbound_heading_deg=solve_wind_triangle(0, 120, 270, wind).true_heading_deg,
            course_deg=90, heading_deg=90, tas_kt=120,
            wind_direction_deg_from=270, wind_speed_kt=wind, distance_nm=10,
        )
        assert expected is not None
        assert parents[1].thirty_degree_cut_seconds == round(expected.seconds)
    assert [zone.model_dump() for zone in zones] == original
    # Both saved JSON with the field and pre-feature JSON without it are accepted.
    parent = parents[1]
    assert NavLogDisplayRow.model_validate_json(parent.model_dump_json()) == parent
    legacy = parent.model_dump()
    del legacy["thirty_degree_cut_seconds"]
    assert NavLogDisplayRow.model_validate(legacy).thirty_degree_cut_seconds is None


def test_merged_parent_cut_cannot_use_distance_after_an_internal_course_change():
    from autonavlog.application.navlog_display import _thirty_degree_cut

    node = uuid4()
    ids = [uuid4() for _ in range(3)]
    source = _summary_zone()
    before = source.model_copy(update={
        "section_id": ids[0], "true_course_deg": _automatic(0),
        "magnetic_heading_deg": _automatic(0), "variation_deg_east": _automatic(0),
    })
    after = source.model_copy(update={
        "section_id": ids[1], "magnetic_course_deg": _automatic(90),
        "magnetic_heading_deg": _automatic(90), "variation_deg_east": _automatic(0),
        "tas_kt": _automatic(120), "wind_speed_kt": _automatic(0),
        "zone_distance_nm": _automatic(0.1),
    })
    later = after.model_copy(update={"section_id": ids[2], "zone_distance_nm": _automatic(20)})
    legs = [
        NavLogPhysicalLeg((ids[0],), FlightPhase.CRUISE, "A", "B", end_node_id=node),
        NavLogPhysicalLeg(tuple(ids[1:]), FlightPhase.CRUISE, "B", "D", start_node_id=node,
                          show_child_courses=True, adopted_distance_nm=20.1),
    ]
    assert _thirty_degree_cut(1, legs, [before, after, later]) is None
    after.zone_distance_nm = _automatic(5)
    assert _thirty_degree_cut(1, legs, [before, after, later]) == 57
