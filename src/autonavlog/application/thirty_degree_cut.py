"""Display-only fly-over interception, in a local east/north frame (NM, seconds).

Headings/courses passed here are true. Subtracting the adopted VAR from MC +/-30
preserves the specified magnetic CUT heading without applying a new WCA.
The adopted next-Leg TAS and wind remain constant throughout the manoeuvre.
"""

from dataclasses import dataclass
from math import atan, ceil, cos, expm1, isfinite, log, radians, sin, sqrt, tan


@dataclass(frozen=True)
class CutSolution:
    seconds: float
    straight_seconds: float
    join_distance_nm: float


def _turn(heading: float, angle: float, bank: float, tas: float) -> tuple[float, float, float]:
    """Return duration and air displacement; angles are radians, TAS is kt.

    Integrate heading analytically through linear bank ramps, then integrate
    velocity with composite Simpson quadrature (at most 0.1 s per interval).
    Small turns have triangular bank profiles instead of overshooting the target.
    """
    if abs(angle) < 1e-12:
        return 0.0, 0.0, 0.0
    gravity_over_speed = 32.174 / (tas * (1852.0 / 0.3048) / 3600.0)
    roll_rate = radians(6.0)
    sign = 1 if angle > 0 else -1
    full_ramp_angle = -2 * gravity_over_speed / roll_rate * log(cos(bank))
    peak = bank if abs(angle) >= full_ramp_angle else atan(sqrt(
        expm1(abs(angle) * roll_rate / gravity_over_speed)
    ))
    ramp_time = peak / roll_rate
    ramp_angle = -gravity_over_speed / roll_rate * log(cos(peak))
    rate = gravity_over_speed * tan(peak)
    hold_time = max(0.0, (abs(angle) - 2 * ramp_angle) / rate)
    east = north = 0.0
    # Splitting at bank-profile corners keeps quadrature smooth within each stage.
    for stage, duration in enumerate((ramp_time, hold_time, ramp_time)):
        if duration == 0:
            continue
        count = max(2, 2 * ceil(duration / 0.2))
        step = duration / count
        for index in range(count + 1):
            time = index * step
            if stage == 0:
                swept = -gravity_over_speed / roll_rate * log(cos(roll_rate * time))
            elif stage == 1:
                swept = ramp_angle + rate * time
            else:
                swept = ramp_angle + rate * hold_time + gravity_over_speed / roll_rate * (
                    log(cos(peak - roll_rate * time)) - log(cos(peak))
                )
            current = heading + sign * swept
            weight = 1 if index in (0, count) else (4 if index % 2 else 2)
            east += weight * sin(current) * step / 3 * tas / 3600
            north += weight * cos(current) * step / 3 * tas / 3600
    return 2 * ramp_time + hold_time, east, north


def solve_thirty_degree_cut(
    *,
    inbound_course_deg: float,
    inbound_heading_deg: float,
    course_deg: float,
    heading_deg: float,
    tas_kt: float,
    wind_direction_deg_from: float,
    wind_speed_kt: float,
    distance_nm: float,
) -> CutSolution | None:
    """Solve initial 30-degree-bank turn, fixed CUT, then 15-degree-bank return.

    Roll starts/ends at wings level at 6 degrees/second. Only nonnegative straight
    durations and a forward, on-course join within the next straight Leg qualify.
    A line crossing with the wrong final ground track is not a solution.
    """
    if not all(isfinite(value) for value in (
        inbound_course_deg, inbound_heading_deg, course_deg, heading_deg, tas_kt,
        wind_direction_deg_from, wind_speed_kt, distance_nm,
    )) or tas_kt <= 0 or wind_speed_kt < 0 or distance_nm <= 0:
        return None
    change = (course_deg - inbound_course_deg + 180) % 360 - 180
    if abs(change) < 1e-7:
        return None
    # The exact reciprocal has no shorter side; consistently choose right.
    sign = 1 if change > 0 or change == -180 else -1
    cut = (course_deg + sign * 30) % 360
    initial_angle = sign * ((sign * (cut - inbound_heading_deg)) % 360)
    return_angle = (heading_deg - cut + 180) % 360 - 180
    course = radians(course_deg)
    wind_east = -wind_speed_kt * sin(radians(wind_direction_deg_from)) / 3600
    wind_north = -wind_speed_kt * cos(radians(wind_direction_deg_from)) / 3600

    def velocity(heading_deg: float) -> tuple[float, float]:
        return (
            tas_kt * sin(radians(heading_deg)) / 3600 + wind_east,
            tas_kt * cos(radians(heading_deg)) / 3600 + wind_north,
        )

    def along(east: float, north: float) -> float:
        return east * sin(course) + north * cos(course)

    def cross(east: float, north: float) -> float:
        return east * cos(course) - north * sin(course)

    final_velocity = velocity(heading_deg)
    if along(*final_velocity) <= 0 or abs(cross(*final_velocity)) > 1e-8:
        return None
    first = _turn(radians(inbound_heading_deg), radians(initial_angle), radians(30), tas_kt)
    last = _turn(radians(cut), radians(return_angle), radians(15), tas_kt)
    turn_time = first[0] + last[0]
    east = first[1] + last[1] + wind_east * turn_time
    north = first[2] + last[2] + wind_north * turn_time
    cut_velocity = velocity(cut)
    cross_speed = cross(*cut_velocity)
    if abs(cross_speed) < 1e-10:
        return None
    straight_time = -cross(east, north) / cross_speed
    if straight_time < 0 or not isfinite(straight_time):
        return None
    east += cut_velocity[0] * straight_time
    north += cut_velocity[1] * straight_time
    join = along(east, north)
    seconds = turn_time + straight_time
    if not isfinite(seconds) or seconds < 0.5 or not 0 < join <= distance_nm:
        return None
    return CutSolution(seconds, straight_time, join)
