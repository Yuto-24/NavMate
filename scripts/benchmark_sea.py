"""Prepare identical synthetic route inputs for the manual SEA browser benchmark."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import types
from pathlib import Path
from uuid import UUID

from geographiclib.geodesic import Geodesic

from autonavlog.application import sea
from tests.unit.test_checkpoints import _cp, _project


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Git ref before the SEA change")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)

    def old(path: str) -> str:
        return subprocess.check_output(
            ["git", "show", f"{args.baseline}:{path}"], cwd=root, text=True
        )

    baseline = types.ModuleType("autonavlog.application._benchmark_baseline")
    baseline.__package__ = "autonavlog.application"
    sys.modules[baseline.__name__] = baseline
    exec(compile(old("src/autonavlog/application/sea.py"), "baseline_sea.py", "exec"),
         baseline.__dict__)
    project = _project()
    start, middle = project.route_nodes
    start.latitude_deg, start.longitude_deg = 31.9, 131.4
    middle.latitude_deg, middle.longitude_deg = 33.0, 130.4
    end = middle.model_copy(deep=True)
    end.id = UUID(int=3)
    end.sequence = 2
    end.latitude_deg, end.longitude_deg = 33.7, 131.1
    project.route_nodes.append(end)
    leg = project.sections[0].model_copy(deep=True)
    leg.id, leg.sequence = UUID(int=4), 1
    leg.from_node_id, leg.to_node_id = middle.id, end.id
    project.sections.append(leg)
    distance_nm = 0.0
    for section, a, b in zip(
        project.sections, project.route_nodes[:-1], project.route_nodes[1:], strict=True
    ):
        line = Geodesic.WGS84.InverseLine(a.latitude_deg, a.longitude_deg,
                                        b.latitude_deg, b.longitude_deg)
        distance_nm += line.s13 / 1852
        for index, fraction in enumerate([.2, .4, .6, .8]):
            point = line.Position(line.s13 * fraction)
            cp = _cp(latitude=point["lat2"], longitude=point["lon2"], name=f"CP{index}")
            cp.linked_section_id = section.id
            project.visual_references.append(cp)
    moved = project.model_copy(deep=True)
    cp = moved.visual_references[1]
    cp.longitude_deg += .00002  # Small exact-boundary move, no CP rounding.
    deleted = moved.model_copy(deep=True)
    del deleted.visual_references[1]
    plans = {
        "baseline_ref": args.baseline, "distance_nm": distance_nm,
        "before": [baseline.sea_plan(p, regions=True) for p in (project, moved, deleted)],
        "after": [sea.sea_plan(p, regions=True) for p in (project, moved, deleted)],
    }
    (args.output / "plans.json").write_text(json.dumps(plans), encoding="utf-8")
    for name in ["sea", "terrain", "terrainTransport"]:
        (args.output / f"before-{name}.ts").write_text(old(f"web/src/{name}.ts"))
    for name in ["sea", "terrain", "terrainTransport", "seaCache"]:
        (args.output / f"after-{name}.ts").write_text((root / f"web/src/{name}.ts").read_text())


if __name__ == "__main__":
    main()
