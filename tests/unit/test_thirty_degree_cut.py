from math import ceil, cos, degrees, log, radians, sin, tan

import pytest

from autonavlog.application.thirty_degree_cut import _turn, solve_thirty_degree_cut
from autonavlog.nav.wind_triangle import solve_wind_triangle


def _request(change=90.0, *, start=0.0, wind=0.0, direction=270.0, tas=120.0, distance=20):
    course = (start + change) % 360
    return dict(
        inbound_course_deg=start,
        inbound_heading_deg=solve_wind_triangle(start, tas, direction, wind).true_heading_deg,
        course_deg=course,
        heading_deg=solve_wind_triangle(course, tas, direction, wind).true_heading_deg,
        tas_kt=tas, wind_direction_deg_from=direction, wind_speed_kt=wind, distance_nm=distance,
    )

def _reference_turn(heading, angle, bank, tas):
    """Independent midpoint ODE integration of bank, heading and air position.

    Find the peak bank by bisection; don't use the production turn integrator.
    The stopping distance in heading determines when roll-out must start.
    """
    rate = radians(6)
    acceleration = 32.174 * 0.3048 / (tas * 1852 / 3600)
    lo, hi = 0.0, radians(bank)
    for _ in range(55):
        mid = (lo + hi) / 2
        if -2 * acceleration / rate * log(cos(mid)) > abs(radians(angle)):
            hi = mid
        else:
            lo = mid
    peak = (lo + hi) / 2
    ramp = peak / rate
    hold = max(0, (abs(radians(angle)) + 2 * acceleration / rate * log(cos(peak)))
               / (acceleration * tan(peak)))
    duration = 2 * ramp + hold
    n = ceil(duration / 0.002)
    dt = duration / n
    psi = radians(heading)
    east = north = 0.0
    for i in range(n):
        t = (i + 0.5) * dt
        phi = min(rate * t, peak, rate * (duration - t))
        dpsi = (1 if angle > 0 else -1) * acceleration * tan(phi) * dt
        east += tas / 3600 * sin(psi + dpsi / 2) * dt
        north += tas / 3600 * cos(psi + dpsi / 2) * dt
        psi += dpsi
    return duration, east, north, degrees(psi)


@pytest.mark.parametrize("angle,bank", [(1, 30), (30, 15), (-120, 30), (210, 30)])
def test_roll_is_part_of_turn_and_motion_including_triangular_bank(angle, bank):
    actual = _turn(radians(355), radians(angle), radians(bank), 120)
    duration, east, north, heading = _reference_turn(355, angle, bank, 120)
    assert actual == pytest.approx((duration, east, north), abs=2e-7)
    assert heading == pytest.approx(355 + angle, abs=2e-6)
    # The naive constant-bank turn plus two full roll times is not this trajectory.
    naive = abs(radians(angle)) / (32.174 * 0.3048 / (120 * 1852 / 3600)
                                  * tan(radians(bank))) + 2 * bank / 6
    assert abs(duration - naive) > 1


@pytest.mark.parametrize("change,start,wind,direction", [
    (60, 0, 0, 0), (-60, 0, 0, 0), (90, 0, 20, 270), (-90, 0, 20, 90),
    (150, 0, 20, 270), (-150, 0, 20, 90), (179, 0, 0, 0), (180, 0, 0, 0),
    (90, 350, 20, 260), (-90, 10, 20, 100), (60, 0, 20, 90),
])
def test_solution_rejoins_with_wings_level_and_planned_heading(change, start, wind, direction):
    request = _request(change, start=start, wind=wind, direction=direction)
    result = solve_thirty_degree_cut(**request)
    assert result is not None
    sign = 1 if change > 0 else -1
    cut = (request["course_deg"] + sign * 30) % 360
    first_angle = sign * ((sign * (cut - request["inbound_heading_deg"])) % 360)
    last_angle = (request["heading_deg"] - cut + 180) % 360 - 180
    first = _reference_turn(request["inbound_heading_deg"], first_angle, 30, 120)
    last = _reference_turn(cut, last_angle, 15, 120)
    assert result.seconds == pytest.approx(first[0] + result.straight_seconds + last[0])
    error = (last[3] - request["heading_deg"] + 180) % 360 - 180
    assert error == pytest.approx(0, abs=2e-6)
    east = first[1] + last[1] + 120 / 3600 * sin(radians(cut)) * result.straight_seconds
    north = first[2] + last[2] + 120 / 3600 * cos(radians(cut)) * result.straight_seconds
    east -= wind / 3600 * sin(radians(direction)) * result.seconds
    north -= wind / 3600 * cos(radians(direction)) * result.seconds
    course = radians(request["course_deg"])
    assert east * cos(course) - north * sin(course) == pytest.approx(0, abs=3e-7)
    assert east * sin(course) + north * cos(course) == pytest.approx(result.join_distance_nm,
                                                                   abs=3e-7)
    assert result.seconds > result.straight_seconds > 0


@pytest.mark.parametrize("change", [0, 1, -5, 20, -30, 45])
def test_no_turn_or_negative_straight_duration_has_no_solution(change):
    assert solve_thirty_degree_cut(**_request(change)) is None


def test_short_leg_and_wrong_final_ground_track_are_not_line_intercepts():
    request = _request()
    valid = solve_thirty_degree_cut(**request)
    assert valid is not None
    too_short = request | {"distance_nm": valid.join_distance_nm - 1e-5}
    assert solve_thirty_degree_cut(**too_short) is None
    assert solve_thirty_degree_cut(**(request | {"distance_nm": valid.join_distance_nm + 1e-5}))
    assert solve_thirty_degree_cut(**(request | {"heading_deg": 91})) is None
    assert solve_thirty_degree_cut(**(request | {"heading_deg": 270})) is None


@pytest.mark.parametrize("key,value", [
    ("tas_kt", 0), ("tas_kt", float("nan")), ("wind_speed_kt", -1),
    ("distance_nm", 0), ("distance_nm", float("inf")), ("heading_deg", float("nan")),
])
def test_invalid_inputs_fail_closed(key, value):
    assert solve_thirty_degree_cut(**(_request() | {key: value})) is None
