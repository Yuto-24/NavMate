"""Explicit open upgrades provenance without rewriting historical calculations or user edits."""
import copy
import json
import runpy
from uuid import uuid4

import pytest
from test_local_calculation import ROOT, LocalApplication, calculate

from autonavlog.local_persistence import migrate_record

GENERATOR = runpy.run_path(str(ROOT / "scripts/reference/build_vrep_catalog.py"))
LEGACY = GENERATOR["legacy_catalog"]()
CURRENT = {
    p["reference_id"]: p for p in json.loads((ROOT / "data/reference/vrep.json").read_text())
}


@pytest.fixture
def local():
    app = LocalApplication(ROOT / "data", forecast_fixture=ROOT / "tests/fixtures/msm")
    yield app
    app.close()


def install_snapshot(project, snapshot):
    node = project["route_nodes"][1]
    node.update(reference_snapshot=copy.deepcopy(snapshot), latitude_deg=snapshot["latitude_deg"],
                longitude_deg=snapshot["longitude_deg"],
                source=f"REFERENCE:{snapshot['reference_id']}")
    return node


def record_from(state):
    project = state["project"]
    return migrate_record(dict(
        schemaVersion=2, id=project["id"], token=str(uuid4()),
        checkpoint=copy.deepcopy(project), draft=copy.deepcopy(project),
        lastCalculation=state["workingRecovery"]["last_calculation"],
        updatedAt=project["updated_at"],
    )).model_dump(mode="json")


def test_all_legacy_points_upgrade_once_preserving_identity_inputs_and_calculation(local):
    base = record_from(calculate(local))
    original_state = local.dispatch("state")
    for legacy in LEGACY:
        record = copy.deepcopy(base)
        for key in ("checkpoint", "draft"):
            install_snapshot(record[key], legacy)["name"] = "利用者の名前"
        before = copy.deepcopy(record)
        updated = json.loads(local.dispatch("prepareReferenceUpdate", record))
        assert record == before
        assert updated["token"] != record["token"]
        assert updated["lastCalculation"] == record["lastCalculation"]
        assert updated["id"] == record["id"]
        for key in ("checkpoint", "draft"):
            new_node = updated[key]["route_nodes"][1]
            current = CURRENT[legacy["reference_id"]]
            assert new_node["reference_snapshot"] == current
            assert new_node["latitude_deg"] == current["latitude_deg"]
            assert new_node["longitude_deg"] == current["longitude_deg"]
            # No section IDs, manual planning values, names or node identities are replaced.
            restored = copy.deepcopy(updated[key])
            restored["updated_at"] = record[key]["updated_at"]
            restored["route_nodes"][1] = record[key]["route_nodes"][1]
            assert restored == record[key]
            assert new_node["id"] == record[key]["route_nodes"][1]["id"]
            assert new_node["name"] == "利用者の名前"
        assert json.loads(local.dispatch("prepareReferenceUpdate", updated)) == updated
    # Preparation must not replace the active work even before a browser write succeeds.
    assert local.dispatch("state") == original_state


@pytest.mark.parametrize("change", ["coordinates", "source", "snapshot", "unknown", "missing"])
def test_edited_or_unidentified_points_remain_unchanged(local, change):
    record = record_from(calculate(local))
    for key in ("checkpoint", "draft"):
        node = install_snapshot(record[key], LEGACY[0])
        if change == "coordinates":
            node["latitude_deg"] += 0.01
        elif change == "source":
            node["source"] = "MANUAL"
        elif change == "snapshot":
            node["reference_snapshot"]["source"]["table_effective_date"] = "2000-01-01"
        elif change == "unknown":
            node["reference_snapshot"]["reference_id"] = "UNKNOWN"
        else:
            node["reference_snapshot"] = None
    assert json.loads(local.dispatch("prepareReferenceUpdate", record)) == record


def test_legacy_open_update_requires_recalculation_and_keeps_last_good_evidence(local):
    state = calculate(local)
    snapshot = next(p for p in LEGACY if p["reference_id"] == "RJFM-VREP-HITOTSUBA")
    install_snapshot(state["workingRecovery"]["project"], snapshot)
    local.dispatch("bootstrap", state["workingRecovery"])
    state = json.loads(local.dispatch("calculate"))
    assert state["readiness"]["calculationIsCurrent"]
    record = record_from(state)
    updated = json.loads(local.dispatch("prepareReferenceUpdate", record))
    restored = json.loads(local.dispatch("bootstrap", {
        **state["workingRecovery"], "project": updated["draft"],
        "last_calculation": updated["lastCalculation"],
    }))
    assert not restored["readiness"]["calculationIsCurrent"]
    assert restored["verticalProfileStale"]
    assert updated["lastCalculation"] == record["lastCalculation"]
    assert restored["project"]["route_nodes"][1]["id"] == record["draft"]["route_nodes"][1]["id"]
    recalculated = json.loads(local.dispatch("calculate"))
    assert recalculated["readiness"]["calculationIsCurrent"]
    new_calculation = recalculated["workingRecovery"]["last_calculation"]["project"]
    assert (new_calculation["route_nodes"][1]["reference_snapshot"]
            == CURRENT[snapshot["reference_id"]])
