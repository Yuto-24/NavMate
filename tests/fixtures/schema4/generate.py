"""Run with the pinned v2.2.2 source/dependencies, not the candidate environment."""
from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from test_local_calculation import ROOT, LocalApplication, calculate

from autonavlog.local_persistence import migrate_record

assert version("autonavlog") == "2.2.2"
assert version("jma-gpv-weather") == "0.5.0"
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
for mode in ("ftd", "msm"):
    app = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    try:
        working = calculate(app, forecast=mode == "msm")["workingRecovery"]
        project = working["project"]
        assert project["schema_version"] == 4 and "selected_forecast_model" not in project
        draft = deepcopy(project)
        draft["pilot_name"] = "unsaved draft"
        record = {"schemaVersion": 2, "id": project["id"], "token": str(uuid4()),
                  "checkpoint": project, "draft": draft,
                  "lastCalculation": working["last_calculation"],
                  "updatedAt": project["updated_at"]}
        migrate_record(record)
        (output / f"{mode}.json").write_text(json.dumps(record))
    finally:
        app.close()
schema = (ROOT / "data/schemas/project.schema.json").read_bytes()
(output / "project.schema.json").write_bytes(schema)
provenance = {"commit": "03cc463cf09192e1403f839df4165410c5db8d7b",
              "app_version": version("autonavlog"), "weather_version": version("jma-gpv-weather"),
              "files": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                        for name in ("ftd.json", "msm.json", "project.schema.json")}}
(output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
