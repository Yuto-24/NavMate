"""Names migrate conservatively without touching the persisted flight or identity."""

import copy

import pytest

from autonavlog.domain.project import Project
from autonavlog.domain.project_naming import refresh_automatic_name
from autonavlog.local_persistence import migrate_record


def automatic(project, *, suffix=""):
    project.name = f"{project.flight_date.isoformat()}_RJFM-RJFO{suffix}"
    project.metadata.update(project_name_auto=True, project_name_generated=project.name)
    return project


@pytest.mark.parametrize("mode,prefix", [("FORECAST", "2026-08-10"), ("FTD", "FTD")])
@pytest.mark.parametrize("with_wp", [False, True])
def test_format_and_user_selected_generated_labels(project, mode, prefix, with_wp):
    raw = automatic(project).model_dump(mode="json")
    raw.update(flight_date="2026-08-10", weather_mode=mode)
    if mode == "FTD":
        raw["ftd_weather"] = {"surface_wind": {"direction_deg_from": 180, "speed_kt": 5},
                              "wind_at_5000_ft": {"direction_deg_from": 270, "speed_kt": 20}}
    raw["route_nodes"][1].update(name="喜入", source="MAP", name_source="GENERATED")
    if not with_wp:
        raw["route_nodes"].pop(1)
        raw["sections"] = []
    restored = Project.model_validate(raw)
    assert restored.name == prefix + "_RJFM-RJFO" + ("_喜入" if with_wp else "")


@pytest.mark.parametrize("source", ["RJFM_DEPARTURE_UMK:v1", "RJFM_EXCEPTION:v1",
                                    "RJFM_INBOUND_ARITA:v1", "RJFM_INBOUND_EXCEPTION:v1"])
def test_synthetic_source_excluded_even_after_user_rename(project, source):
    raw = automatic(project).model_dump(mode="json")
    raw["route_nodes"][1].update(name="UMK", source=source, name_source="USER")
    restored = Project.model_validate(raw)
    assert restored.name.endswith("RJFM-RJFO")
    restored.route_nodes[1].source = "MAP"
    refresh_automatic_name(restored)
    assert restored.name.endswith("RJFM-RJFO_UMK")


@pytest.mark.parametrize("metadata", [{}, {"project_name_auto": False},
                                     {"project_name_auto": True},
                                     {"project_name_auto": True,
                                      "project_name_generated": "other"}])
def test_unknown_or_manual_name_is_never_inferred(project, metadata):
    raw = project.model_dump(mode="json")
    raw["metadata"] = metadata
    raw["name"] = "2026-08-10_RJFM-RJFO"
    assert Project.model_validate(raw).model_dump(mode="json") == raw


def test_long_names_collision_ordinal_and_repeated_refresh(project):
    automatic(project)
    project.metadata["project_name_format"] = 2
    project.route_nodes[1].name = "喜入/?" * 30
    refresh_automatic_name(project)
    base = project.name
    assert len(base) == 60 and "/" not in base and "?" not in base
    refresh_automatic_name(project, {base, base[:58] + "_2"})
    assert project.name == base[:58] + "_3"
    before = project.model_dump(mode="json")
    refresh_automatic_name(project, {base, base[:58] + "_2"})
    assert project.model_dump(mode="json") == before


def test_migration_preserves_ordinal_identity_checkpoint_and_timestamps(project):
    from uuid import uuid4

    raw = automatic(project, suffix="_12").model_dump(mode="json")
    record = dict(schemaVersion=2, id=raw["id"], token=str(uuid4()), draft=raw,
                  checkpoint=copy.deepcopy(raw), lastCalculation=None, updatedAt=raw["updated_at"])
    original = copy.deepcopy(record)
    migrated = migrate_record(record).model_dump(mode="json")
    assert record == original
    assert migrated["draft"]["name"].endswith("_TP1_12")
    assert migrated["checkpoint"] == migrated["draft"]
    for key in ("id", "token", "updatedAt", "lastCalculation"):
        assert migrated[key] == record[key]
    for key in raw.keys() - {"name", "metadata"}:
        assert migrated["draft"][key] == raw[key]
    assert migrate_record(migrated).model_dump(mode="json") == migrated
