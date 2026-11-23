"""Credential-free actual-version probe for the supported AIP migration.

Invoked inside each exact application's test image, with synthetic data only.
"""

import copy
import json
import sys
from pathlib import Path
from uuid import uuid4

from autonavlog.local import LocalApplication
from autonavlog.local_persistence import migrate_record

ROOT = Path("/opt/autonavlog")
sys.path.insert(0, str(ROOT / "tests/integration"))


def generate():
    from test_local_calculation import calculate

    application = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    try:
        state = calculate(application)
        project = state["project"]
        record = migrate_record(
            dict(
                schemaVersion=2,
                id=project["id"],
                token=str(uuid4()),
                checkpoint=copy.deepcopy(project),
                draft=copy.deepcopy(project),
                lastCalculation=state["workingRecovery"]["last_calculation"],
                updatedAt=project["updated_at"],
            )
        ).model_dump(mode="json")
        record["draft"]["pilot_name"] = "synthetic unsaved draft"
        latest = copy.deepcopy(record)
        latest["checkpoint"] = None
        print(
            json.dumps(
                {
                    "app_version": (ROOT / "VERSION").read_text().strip(),
                    "saved": record,
                    "latest": latest,
                }
            )
        )
    finally:
        application.close()


def verify(path):
    data = json.loads(Path(path).read_text())
    application = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    try:
        for name in ("saved", "latest"):
            original = data[name]
            # Schema 5 and the portable record version do not change in this migration.
            assert migrate_record(original).model_dump(mode="json") == original
            assert json.loads(application.dispatch("validateRecord", original)) == original
            last = original["lastCalculation"]
            recovery = {
                "version": 1,
                "project": original["draft"],
                "last_calculation": last,
                "outcome": last["outcome"],
                "destination_wind": last["destination_wind"],
                "import_result": None,
                "import_filename": None,
            }
            application.dispatch("bootstrap", recovery)
            restored = json.loads(
                application.dispatch(
                    "refreshSavedWork", {"working": recovery, "rounding_mode": False}
                )
            )
            # The persistence contract strips rederived CUT display values on save.
            # Compare the full durable record through that existing serializer.
            hydrated = {
                **original,
                "lastCalculation": restored["workingRecovery"]["last_calculation"],
            }
            assert migrate_record(hydrated).model_dump(mode="json") == original
            assert restored["project"]["id"] == original["id"]
            assert restored["project"]["pilot_name"] == "synthetic unsaved draft"
            assert restored["project"]["route_nodes"] == original["draft"]["route_nodes"]
            assert restored["readiness"]["calculationIsCurrent"] is False
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "old_version": data["app_version"],
                    "candidate_version": (ROOT / "VERSION").read_text().strip(),
                    "records": ["Saved", "distinct Draft", "Latest", "LastCalculation"],
                    "normalization": "Existing durable CUT display serialization only",
                }
            )
        )
    finally:
        application.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["generate"]:
        generate()
    elif len(sys.argv) == 3 and sys.argv[1] == "verify":
        verify(sys.argv[2])
    else:
        raise SystemExit("Explicit generate or verify required")
