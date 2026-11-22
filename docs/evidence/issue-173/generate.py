"""Generate acceptance inputs with the real calculation and shared projection.

Run from the repository root in the supported test environment. These FTD cases
are reproducible test plans, not operational flight plans or Earth acceptance.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from autonavlog.application.vertical_profile import project_vertical_profile
from autonavlog.domain.calculation import CalculationOutcome
from autonavlog.domain.project import Project
from autonavlog.local import LocalApplication
from scripts.local_reference import reference_state

ROOT = Path(__file__).resolve().parents[3]


def return_state(rate: int) -> dict:
    inputs = json.loads((ROOT / "tests/fixtures/issue_117_ftd.json").read_text())["confirm"]
    points = [
        ("RJFO", 33.47949406702627, 131.7371201529664),
        ("ENROUTE", 32.7, 131.6),
        ("小丸", 32.16255070087476, 131.47036916946163),
        ("RJFM", 31.8772222222, 131.4486111111),
    ]
    app = LocalApplication(ROOT / "data")
    try:
        state = json.loads(app.dispatch("confirmRoute", {
            **inputs, "candidate_kind": "map", "descent_rate_fpm": rate,
            "map_points": [
                {"name": name, "latitude_deg": lat, "longitude_deg": lon,
                 "airport_id": name if name in {"RJFO", "RJFM"} else None}
                for name, lat, lon in points
            ],
        }))
        app.dispatch("updateProject", {
            **{key: inputs[key] for key in (
                "flight_date", "departure_time_jst", "weather_mode", "ftd_weather",
                "default_variation_deg_east",
            )},
            "total_usable_fuel_gal": 90, "selected_pattern_altitude_ft_msl": 1000,
            "visual_reporting_point_node_id": state["project"]["route_nodes"][-2]["id"],
            "descent_rate_fpm": rate,
        })
        return json.loads(app.dispatch("calculate"))
    finally:
        app.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, state in (
        ("general-ftd", reference_state(local=True, manual=True)),
        ("rjfm-return-500", return_state(500)),
        ("rjfm-return-1000", return_state(1000)),
    ):
        assert state["readiness"]["calculationIsCurrent"]
        saved = state["workingRecovery"]["last_calculation"]
        project = Project.model_validate_json(json.dumps(saved["project"]))
        outcome = CalculationOutcome.model_validate_json(json.dumps(saved["outcome"]))
        profile = asdict(project_vertical_profile(project, outcome))
        assert json.loads(json.dumps(profile)) == json.loads(json.dumps(state["verticalProfile"]))
        assert not outcome.blockers
        # Round-trip the saved calculation; no working Project or solver is used.
        assert asdict(project_vertical_profile(
            Project.model_validate_json(project.model_dump_json()),
            CalculationOutcome.model_validate_json(outcome.model_dump_json()),
        )) == profile
        for suffix, value in (("last-calculation", saved), ("profile", profile)):
            (args.output / f"{name}.{suffix}.json").write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )


if __name__ == "__main__":
    main()
