"""Common facade behavior and durable Local/Legacy automatic-name migration."""

import copy
import json
from uuid import UUID, uuid4

import pytest

from autonavlog.local_persistence import migrate_record
from autonavlog.web.models import SaveProjectRequest
from tests.integration.test_issue_94_facade_persistence import _application, _new_project
from tests.integration.test_local_calculation import calculate, local  # noqa: F401
from tests.integration.test_map_route import edit_payload, payload, point


@pytest.mark.parametrize("mode", ["FTD", "FORECAST"])
@pytest.mark.parametrize("with_wp", [False, True])
def test_local_map_confirmation_and_reconfirmation(local, mode, with_wp):  # noqa: F811
    points = [point("FROM", airport="RJFM")]
    if with_wp:
        points += [point("喜入", 32.1156, 130.3376), point("加茂", 32.89, 130.53)]
    points += [point("TO", airport="RJFS")]
    request = {**payload(points), "weather_mode": mode}
    state = json.loads(local.dispatch("confirmRoute", request))
    prefix = "FTD" if mode == "FTD" else request["flight_date"]
    expected = prefix + "_RJFM-RJFS" + ("_喜入-加茂" if with_wp else "")
    assert state["project"]["name"] == expected
    if with_wp:
        changed = edit_payload(state["project"])
        changed["map_points"].pop(1)
        state = json.loads(local.dispatch("confirmRoute", changed))
        assert state["project"]["name"] == prefix + "_RJFM-RJFS_加茂"


def test_local_rename_migration_sync_and_manual_protection(local):  # noqa: F811
    calculated = calculate(local)
    assert calculated["project"]["name"] == "FTD_RJFM-RJFS_米ノ津-玉名-大牟田"
    renamed = json.loads(local.dispatch("renameRouteNode", {
        "node_id": calculated["project"]["route_nodes"][1]["id"], "name": "喜入",
    }))
    assert renamed["project"]["name"] == "FTD_RJFM-RJFS_喜入-玉名-大牟田"
    assert renamed["outcome"]["summary"] == calculated["outcome"]["summary"]
    assert renamed["outcome"]["fuel_plan"] == calculated["outcome"]["fuel_plan"]
    assert renamed["project"]["sections"] == calculated["project"]["sections"]
    assert renamed["readiness"]["calculationIsCurrent"]
    assert (renamed["workingRecovery"]["last_calculation"]
            == calculated["workingRecovery"]["last_calculation"])
    raw = copy.deepcopy(calculated["workingRecovery"])
    for project in [raw["project"], raw["last_calculation"]["project"]]:
        project["name"] = project["flight_date"] + "_RJFM-RJFS"
        project["metadata"]["project_name_generated"] = project["name"]
        project["metadata"].pop("project_name_format")
        project["metadata"].pop("project_name_base")
    record = dict(schemaVersion=2, id=raw["project"]["id"], token=str(uuid4()),
                  draft=raw["project"], checkpoint=copy.deepcopy(raw["project"]),
                  lastCalculation=raw["last_calculation"], updatedAt=raw["project"]["updated_at"])
    migrated = migrate_record(record).model_dump(mode="json")
    assert migrated["lastCalculation"]["outcome"] == record["lastCalculation"]["outcome"]
    assert (migrated["lastCalculation"]["calculation_fingerprint"]
            == record["lastCalculation"]["calculation_fingerprint"])
    resolved = json.loads(local.dispatch("prepareSyncResolution", {"record": migrated}))
    assert resolved == migrated
    restored = json.loads(local.dispatch("bootstrap", raw))
    assert restored["project"]["name"] == calculated["project"]["name"]
    assert restored["outcome"] == calculated["outcome"]
    assert restored["readiness"]["calculationIsCurrent"]
    manual = restored["workingRecovery"]
    manual["project"]["name"] = "訓練用"
    manual["project"]["metadata"]["project_name_auto"] = False
    local.dispatch("adoptSavedProject", {"working": manual})
    renamed = json.loads(local.dispatch("renameRouteNode", {
        "node_id": manual["project"]["route_nodes"][1]["id"], "name": "加茂",
    }))
    changed = edit_payload(renamed["project"])
    changed["map_points"].pop(2)
    confirmed = json.loads(local.dispatch("confirmRoute", changed))
    restored = json.loads(local.dispatch("bootstrap", confirmed["workingRecovery"]))
    assert restored["project"]["name"] == "訓練用"


def test_legacy_save_duplicate_name_manual_protection_and_read_migration(tmp_path):
    app = _application(tmp_path)
    session, state = _new_project(app)
    name = state["project"]["name"]
    assert name.startswith("FTD_RJFM-RJFO_")
    saved = app.save(session, SaveProjectRequest(name=name))
    assert saved["project"]["metadata"]["project_name_auto"] is True
    other, second = _new_project(app)
    assert second["project"]["name"] == name + "_2"
    renamed = app.rename_route_node(session, session.project.route_nodes[1].id, "喜入")
    assert "_喜入-" in renamed["project"]["name"]
    app.save(session, SaveProjectRequest(name="手動名"))
    app.rename_route_node(session, session.project.route_nodes[1].id, "加茂")
    assert app.load(session, session.project.id)["project"]["name"] == "手動名"
    # A checkpoint written by an older client is upgraded through the same
    # Project reader used by the portable envelope, without a revision bump.
    app.save(other, SaveProjectRequest())
    project = other.project.model_dump(mode="json")
    project["name"] = project["flight_date"] + "_RJFM-RJFO_2"
    project["metadata"]["project_name_generated"] = project["name"]
    project["metadata"].pop("project_name_format")
    project["metadata"].pop("project_name_base")
    path = tmp_path / "projects" / project["id"] / "project.json"
    assert path.exists()
    path.write_text(json.dumps(project), encoding="utf-8")
    loaded = app.project_service.repository.load_checkpoint(UUID(project["id"]))
    assert loaded.name == name + "_2"
    assert loaded.id == other.project.id and loaded.revision == other.project.revision
    summaries = app.project_service.list_projects()
    assert next(item.name for item in summaries if item.id == loaded.id) == loaded.name
