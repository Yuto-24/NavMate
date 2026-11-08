from __future__ import annotations

import json

import pytest
from test_local_calculation import calculate
from test_local_calculation import local as local

from autonavlog.domain.calculation import Issue
from autonavlog.domain.enums import IssueSeverity


def test_stale_recovery_discards_historical_diagnostics_but_validates_current_route(local):
    state = calculate(local)
    recovery = state["workingRecovery"]
    historical = [
        Issue(code=code, severity=IssueSeverity.BLOCKER, message="historical").model_dump(
            mode="json"
        )
        for code in ("FLIGHT_PHASE_SEQUENCE_INVALID", "RJFM_INBOUND_DIRECT_DISTANCE_SHORTFALL")
    ]
    recovery["outcome"]["issues"] = historical
    recovery["project"]["total_usable_fuel_gal"] = 75
    restored = json.loads(local.dispatch("bootstrap", recovery))
    assert not restored["readiness"]["calculationIsCurrent"]
    assert {issue["code"] for issue in restored["readiness"]["issues"]} == {
        "RECALCULATION_REQUIRED"
    }
    assert restored["outcome"]["issues"] == historical
    assert restored["workingRecovery"]["last_calculation"] == recovery["last_calculation"]

    # A current violation with the same code must still prevent calculation.
    update = {
        "flight_date": "2026-09-11",
        "departure_time_jst": "09:00",
        "total_usable_fuel_gal": 75,
        "default_variation_deg_east": 8,
        "weather_mode": "FTD",
        "ftd_weather": restored["project"]["ftd_weather"],
        "sections": [
            {
                "section_id": section["id"],
                "phase": "CLIMB",
                "planned_altitude_ft_msl": section["planned_altitude_ft_msl"],
            }
            for section in restored["project"]["sections"][:2]
        ],
    }
    invalid = json.loads(local.dispatch("updateProject", update))
    current = next(
        issue
        for issue in invalid["readiness"]["issues"]
        if issue["code"] == "FLIGHT_PHASE_SEQUENCE_INVALID"
    )
    assert current["severity"] == "BLOCKER"
    assert current["sectionId"] == restored["project"]["sections"][1]["id"]
    assert current["message"] != "historical"
    update["sections"][1]["phase"] = "CRUISE"
    repaired = json.loads(local.dispatch("updateProject", update))
    assert all(
        issue["code"] != "FLIGHT_PHASE_SEQUENCE_INVALID"
        for issue in repaired["readiness"]["issues"]
    )
    result = json.loads(local.dispatch("calculate"))
    assert result["readiness"]["calculationIsCurrent"]
    assert result["outcome"]["issues"] == []
    assert result["workingRecovery"]["last_calculation"] != recovery["last_calculation"]


@pytest.mark.parametrize("operation", ["calculate", "updateAndRecalculate"])
@pytest.mark.parametrize("failure", ["blocker", "exception"])
def test_failed_recalculation_preserves_last_good(local, monkeypatch, operation, failure):
    previous = calculate(local)
    blocked = local.session.outcome.model_copy(
        update={
            "issues": [
                Issue(
                    code="WIND_TRIANGLE_FAILED",
                    severity=IssueSeverity.BLOCKER,
                    message="wind failed",
                )
            ]
        }
    )
    def fail(*args, **kwargs):
        if failure == "exception":
            raise RuntimeError("calculation failed")
        return blocked, None

    monkeypatch.setattr(local.app, "_calculate_outcome", fail)
    payload = (
        {}
        if operation == "calculate"
        else {
            "flight_date": "2026-09-11",
            "departure_time_jst": "09:00",
            "total_usable_fuel_gal": 75,
            "default_variation_deg_east": 8,
            "weather_mode": "FTD",
            "ftd_weather": previous["project"]["ftd_weather"],
        }
    )
    failed = json.loads(local.dispatch_response(operation, payload))
    if failure == "exception":
        assert failed["error"]["code"] == (
            "CALCULATION_JOB_FAILED" if operation == "calculate" else "REQUEST_FAILED"
        )
    else:
        assert failed["outcome"]["issues"][0]["code"] == "WIND_TRIANGLE_FAILED"
    current = json.loads(local.dispatch("state"))
    assert (
        current["workingRecovery"]["last_calculation"]
        == previous["workingRecovery"]["last_calculation"]
    )
    if failure == "exception":
        assert {k: v for k, v in current["outcome"].items() if k != "status"} == {
            k: v for k, v in previous["outcome"].items() if k != "status"
        }
