from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from math import isfinite
from typing import Any

from autonavlog.domain.airport_vor import AIRPORT_VORS
from autonavlog.domain.planning import DepartureVorSelection

VARIATION_LATITUDE_THRESHOLD_DEG = 32.0
VARIATION_NORTH_DEG_EAST = 8.0
VARIATION_SOUTH_DEG_EAST = 7.0
VARIATION_RULE_VERSION = "DEPARTURE_LATITUDE_32N_V1"


@dataclass(frozen=True)
class VariationDecision:
    degrees_east: float
    metadata: dict[str, Any]


def variation_for_departure_latitude(latitude_deg: float) -> VariationDecision:
    """Resolve additive (west-positive) variation from a leg's departure latitude.

    The 32.0 N boundary belongs to the northern band. Invalid coordinates are
    rejected instead of silently falling back to either operational value.
    """

    latitude = float(latitude_deg)
    if not isfinite(latitude) or not -90.0 <= latitude <= 90.0:
        raise ValueError("departure latitude must be finite and within [-90, 90]")
    north_band = latitude >= VARIATION_LATITUDE_THRESHOLD_DEG
    degrees_east = VARIATION_NORTH_DEG_EAST if north_band else VARIATION_SOUTH_DEG_EAST
    return VariationDecision(
        degrees_east=degrees_east,
        metadata={
            "rule_version": VARIATION_RULE_VERSION,
            "method": "LEG_DEPARTURE_LATITUDE_BAND",
            "departure_latitude_deg": latitude,
            "threshold_latitude_deg": VARIATION_LATITUDE_THRESHOLD_DEG,
            "threshold_inclusive_side": "NORTH",
            "selected_band": "NORTH" if north_band else "SOUTH",
            "degrees_east": degrees_east,
        },
    )


VOR_VARIATION_RULE_VERSION = "DEPARTURE_VOR_DECLINATION_V1"

# The same canonical resource is imported directly by web/src/vorRadial.ts.
_vor_data = json.loads(files("autonavlog.nav").joinpath("data/vor_stations.json").read_text())
VOR_DECLINATIONS: dict[str, tuple[float, str]] = {
    station["identifier"]: (
        station["variation_west_deg"],
        f"AIP {station['variation_source']}; {station['source_file']} p.{station['source_page']}",
    )
    for station in (*_vor_data["stations"], *_vor_data["departure_only_stations"])
}


def variation_for_departure_vor(selection: DepartureVorSelection) -> VariationDecision:
    """Resolve the station reference without falling back to latitude bands."""
    station = AIRPORT_VORS.get(selection.airport_id)
    record = VOR_DECLINATIONS.get(selection.identifier)
    if (
        station is None
        or record is None
        or selection.identifier != station.identifier
        or abs(selection.latitude_deg - station.latitude_deg) > 1e-9
        or abs(selection.longitude_deg - station.longitude_deg) > 1e-9
    ):
        raise ValueError("departure VOR does not match a station with published declination")
    west, source = record
    if not isfinite(west) or not -180 <= west <= 180 or not source:
        raise ValueError("published departure VOR declination is unavailable")
    return VariationDecision(
        degrees_east=west,  # Legacy field name; MC adds west-positive VAR.
        metadata={
            "rule_version": VOR_VARIATION_RULE_VERSION,
            "method": "DEPARTURE_VOR_DECLINATION",
            "identifier": selection.identifier,
            "variation_west_deg": west,
            "source": source,
        },
    )
