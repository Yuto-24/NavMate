from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from autonavlog.domain.project import Project
from autonavlog.local_persistence import migrate_record


def record():
    project = Project(
        name="durable",
        flight_date="2026-09-15",
        planned_departure_time_jst="2026-09-15T09:00:00+09:00",
        departure_airport_id="RJFM",
        destination_airport_id="RJFT",
        total_usable_fuel_gal=90,
        default_variation_deg_east=-8,
    ).model_dump(mode="json")
    return {
        "schemaVersion": 2,
        "id": project["id"],
        "token": str(uuid4()),
        "checkpoint": None,
        "draft": project,
        "lastCalculation": None,
        "updatedAt": datetime.now(UTC).isoformat(),
    }


def test_old_schema_migration_is_pure_and_validated():
    original = record()
    original["schemaVersion"] = 1
    del original["updatedAt"]
    before = copy.deepcopy(original)
    migrated = migrate_record(original)
    assert migrated.schemaVersion == 2
    assert migrated.updatedAt == migrated.draft.updated_at
    assert original == before


def test_run_only_project_migrates_to_msm_without_mutating_source():
    original = record()
    original["draft"]["schema_version"] = 4
    original["draft"].pop("selected_forecast_model", None)
    original["draft"]["selected_forecast_run_id"] = "20260915000000"
    before = copy.deepcopy(original)
    migrated = migrate_record(original)
    assert migrated.draft.schema_version == 5
    assert migrated.draft.selected_forecast_model == "MSM"
    assert migrated.draft.selected_forecast_run_id == "20260915000000"
    assert original == before


def test_gsm_round_trip_keeps_model_separate_from_run():
    original = record()
    original["draft"]["selected_forecast_model"] = "GSM"
    original["draft"]["selected_forecast_run_id"] = "20260915000000"
    restored = migrate_record(migrate_record(original).model_dump(mode="json"))
    assert restored.draft.selected_forecast_model == "GSM"
    assert restored.draft.selected_forecast_run_id == "20260915000000"


@pytest.mark.parametrize(
    "damage", ["version", "identity", "checkpoint", "draft", "owner", "calculation"]
)
def test_migration_or_corruption_failure_never_modifies_original(damage):
    original = record()
    if damage == "version":
        original["schemaVersion"] = 999
    elif damage == "identity":
        original["id"] = str(uuid4())
    elif damage == "checkpoint":
        original["checkpoint"] = copy.deepcopy(original["draft"])
        original["checkpoint"]["revision"] += 1
    elif damage == "draft":
        original["draft"] = {"id": original["id"]}
    elif damage == "owner":
        original["draft"]["metadata"]["web_owner_id"] = "legacy"
    else:
        original["lastCalculation"] = {"calculation_fingerprint": "bad"}
    before = copy.deepcopy(original)
    with pytest.raises((ValidationError, ValueError)):
        migrate_record(original)
    assert original == before
    assert migrate_record(record()).schemaVersion == 2


@pytest.mark.parametrize("seconds", [0, 14, 999])
def test_durable_cut_projection_preserves_plan_and_is_readable_by_old_clients(seconds):
    fixture = Path(__file__).resolve().parents[1] / "fixtures/schema4/ftd.json"
    original = json.loads(fixture.read_text())
    model = migrate_record(original)
    assert model.lastCalculation is not None
    for row in model.lastCalculation.outcome.display_rows:
        row.thirty_degree_cut_seconds = seconds
    before = model.model_dump(mode="python")
    expected = model.lastCalculation.model_dump(mode="json")
    for row in expected["outcome"]["display_rows"]:
        row["thirty_degree_cut_seconds"] = None
    serialized = model.model_dump(mode="json")
    assert serialized["lastCalculation"] == expected
    assert json.loads(model.model_dump_json()) == serialized
    assert model.model_dump(mode="python") == before
    assert migrate_record(serialized).model_dump(mode="json") == serialized
