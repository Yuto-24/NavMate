"""Versioned input-only Project exchange; never a repository serialization."""
from __future__ import annotations

import json
import math
from typing import Any

from autonavlog.application.project_service import ProjectService
from autonavlog.application.sea import POLICY, SeaRecord, legacy_interval_keys, sea_plan
from autonavlog.domain.planning import PersistedUiState
from autonavlog.domain.project import Project
from autonavlog.web.models import UpdateProjectRequest

MAX_BYTES = 2 * 1024 * 1024
PROJECT_FIELDS = (
    "name", "pilot_name", "ship_identifier", "flight_date",
    "planned_departure_time_jst", "departure_airport_id", "destination_airport_id",
    "aircraft_profile_id", "total_usable_fuel_gal", "default_variation_deg_east",
    "weather_mode", "ftd_weather", "run_up_included", "nose_fairing_enabled",
    "air_conditioning_enabled", "descent_rate_fpm", "tgl_count",
    "route_nodes", "visual_references", "sections",
)
UI_FIELDS = (
    "departure_vor", "arrival_plan", "reference_data_snapshot",
    "rjfm_departure_plan", "rjfm_inbound_plan",
)


def _bounded(value: Any, depth: int = 0) -> None:
    if depth > 24:
        raise ValueError("JSON nesting exceeds 24")
    if isinstance(value, dict):
        if len(value) > 4096:
            raise ValueError("too many object entries")
        for key, item in value.items():
            _bounded(key, depth + 1)
            _bounded(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 4096:
            raise ValueError("too many list entries")
        for item in value:
            _bounded(item, depth + 1)
    elif isinstance(value, str) and len(value) > 4096:
        raise ValueError("text exceeds 4096 characters")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite number")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _require_fields(raw: Any, canonical: Any) -> None:
    # v1 exports complete nested objects. Domain defaults are useful for stored
    # legacy records, but must not silently repair an external exchange file.
    if isinstance(canonical, dict):
        if not isinstance(raw, dict) or raw.keys() != canonical.keys():
            raise ValueError("missing or unknown nested Project input")
        for key in canonical:
            _require_fields(raw[key], canonical[key])
    elif isinstance(canonical, list):
        for supplied, expected in zip(raw, canonical, strict=True):
            _require_fields(supplied, expected)


def export_project(project: Project) -> str:
    raw = project.model_dump(mode="json")
    ui = ProjectService.ui_state(project).model_dump(mode="json")
    manual = {item["key"]: item["manual_ft"] for item in sea_plan(project)["intervals"]
              if item["manual_ft"] is not None}
    payload = {"format": "navmate.project", "version": 1,
               "inputs": {key: raw[key] for key in PROJECT_FIELDS},
               "planning": {key: ui[key] for key in UI_FIELDS}, "manual_sea": manual}
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    # Export and import have the same contract and budgets.
    import_project(text)
    return text


def import_project(text: str) -> Project:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Project JSON exceeds 2 MiB")
    payload = json.loads(text, object_pairs_hook=_object)
    _bounded(payload)
    if not isinstance(payload, dict) or set(payload) != {
        "format", "version", "inputs", "planning", "manual_sea"
    }:
        raise ValueError("expected a Project JSON document")
    if payload["format"] != "navmate.project":
        raise ValueError("unsupported format; NAV LOG JSON is not a Project")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("unsupported Project JSON version")
    inputs, planning, manual = payload["inputs"], payload["planning"], payload["manual_sea"]
    if not isinstance(inputs, dict) or set(inputs) != set(PROJECT_FIELDS):
        raise ValueError("missing or unknown Project input")
    if not isinstance(planning, dict) or set(planning) != set(UI_FIELDS):
        raise ValueError("missing or unknown planning input")
    for key in ("route_nodes", "sections", "visual_references"):
        if not isinstance(inputs[key], list) or len(inputs[key]) > 500:
            raise ValueError(f"{key} must contain at most 500 entries")
    for key, limit in (("name", 60), ("pilot_name", 100), ("ship_identifier", 100)):
        if not isinstance(inputs[key], str) or len(inputs[key]) > limit:
            raise ValueError(f"{key} exceeds {limit} characters")
    project = Project.model_validate_json(json.dumps(inputs), strict=True)
    ui = PersistedUiState.model_validate_json(json.dumps(planning), strict=True)
    canonical = project.model_dump(mode="json")
    canonical_ui = ui.model_dump(mode="json")
    _require_fields(inputs, {key: canonical[key] for key in PROJECT_FIELDS})
    _require_fields(planning, {key: canonical_ui[key] for key in UI_FIELDS})
    # Apply the same flight-input ranges as normal editing, without adopting
    # request defaults or changing the imported values.
    edit = {key: value for key, value in inputs.items()
            if key in UpdateProjectRequest.model_fields and key != "sections"}
    edit["departure_time_jst"] = project.planned_departure_time_jst.strftime("%H:%M")
    edit["sections"] = [
        {"section_id": section["id"], **{key: value for key, value in section.items()
            if key not in {"id", "sequence", "from_node_id", "to_node_id"}}}
        for section in inputs["sections"]
    ]
    UpdateProjectRequest.model_validate_json(json.dumps(edit), strict=True)
    nodes = {node.id for node in project.route_nodes}
    sections = {section.id for section in project.sections}
    references = {ref.id for ref in project.visual_references}
    if (len(references) != len(project.visual_references)
            or nodes & sections or nodes & references or sections & references):
        raise ValueError("duplicate Check Point ID")
    if len(nodes) < 2 or not sections:
        raise ValueError("confirmed route is required")
    for group in (project.route_nodes, project.sections):
        if sorted(item.sequence for item in group) != list(range(len(group))):
            raise ValueError("invalid route sequence")
    ordered_nodes, ordered_sections = project.ordered_nodes(), project.ordered_sections()
    if len(ordered_sections) != len(ordered_nodes) - 1 or any(
        section.from_node_id != ordered_nodes[index].id
        or section.to_node_id != ordered_nodes[index + 1].id
        for index, section in enumerate(ordered_sections)
    ):
        raise ValueError("sections must connect consecutive route nodes")
    for ref in project.visual_references:
        if ref.linked_section_id is not None and ref.linked_section_id not in sections:
            raise ValueError("Check Point references an unknown section")
    if ui.arrival_plan and ui.arrival_plan.visual_reporting_point_node_id not in nodes:
        raise ValueError("arrival references an unknown node")
    if ui.departure_vor and ui.departure_vor.airport_id != project.departure_airport_id:
        raise ValueError("departure VOR references a different airport")
    if ui.reference_data_snapshot:
        snapshot = ui.reference_data_snapshot
        if (snapshot.departure_airport.id != project.departure_airport_id
                or snapshot.destination_airport.id != project.destination_airport_id
                or not set(snapshot.route_points) <= nodes
                or not set(snapshot.check_points) <= references):
            raise ValueError("reference snapshot does not match the route")
    if ui.rjfm_inbound_plan:
        plan = ui.rjfm_inbound_plan
        if (not {plan.omaru_node_id, plan.umk_node_id, plan.vrep_node_id} <= nodes
                or not {plan.controlled_section_id, *plan.controlled_section_ids} <= sections):
            raise ValueError("arrival profile does not match the route")
    project.metadata = {"ui_state": ui.model_dump(mode="json")}
    if not isinstance(manual, dict):
        raise ValueError("invalid manual SEA")
    valid_keys = {item["key"] for item in sea_plan(project)["intervals"]}
    legacy_keys = legacy_interval_keys(project)
    if not set(manual) <= valid_keys | legacy_keys.keys():
        raise ValueError("manual SEA references an unknown interval")
    mapped = {legacy_keys.get(key, key): value for key, value in manual.items()}
    if len(mapped) != len(manual):
        raise ValueError("duplicate manual SEA interval")
    records = {key: SeaRecord.model_validate_json(json.dumps({"manual_ft": value}), strict=True)
               for key, value in mapped.items()}
    project.metadata["sea"] = {"policy": POLICY, "records": {
        key: record.model_dump(mode="json") for key, record in records.items()}}
    return project
