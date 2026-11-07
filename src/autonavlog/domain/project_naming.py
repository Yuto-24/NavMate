"""Automatic display names shared by Legacy and portable Project readers."""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .project import Project


def normalize_project_name(value: str) -> str:
    normalized = "".join(
        "_" if character in '<>:"/\\|?*' or ord(character) < 32 else character
        for character in value.strip()
    ).strip()
    return normalized[:60].rstrip(" .") or "route"


def automatic_project_name(project: Project) -> str:
    prefix = "FTD" if project.weather_mode == "FTD" else project.flight_date.isoformat()
    snapshot = project.metadata.get("ui_state", {}).get("reference_data_snapshot") or {}
    departure = (snapshot.get("departure_airport") or {}).get("icao")
    destination = (snapshot.get("destination_airport") or {}).get("icao")
    base = (
        f"{prefix}_{departure or project.departure_airport_id}"
        f"-{destination or project.destination_airport_id}"
    )
    # Name provenance is not point provenance: a clicked MAP/reference point
    # can have a GENERATED label, and a synthetic point can be renamed by a user.
    names = [
        node.name for node in project.ordered_nodes()[1:-1]
        if not node.source.startswith((
            "RJFM_DEPARTURE_UMK:", "RJFM_EXCEPTION:",
            "RJFM_INBOUND_ARITA:", "RJFM_INBOUND_EXCEPTION:",
        ))
    ]
    return normalize_project_name(base + ("_" + "-".join(names) if names else ""))


def has_automatic_name(project: Project) -> bool:
    return (
        project.metadata.get("project_name_auto") is True
        and project.metadata.get("project_name_generated") == project.name
    )


def refresh_automatic_name(project: Project, existing: Collection[str] = ()) -> None:
    if not has_automatic_name(project):
        return
    base = automatic_project_name(project)
    if project.metadata.get("project_name_base") == base and project.name not in existing:
        return
    name = base
    ordinal = 2
    while name in existing:
        suffix = f"_{ordinal}"
        name = f"{base[:60 - len(suffix)]}{suffix}"
        ordinal += 1
    # Avoid assignment validators re-entering the read migration mid-update.
    object.__setattr__(project, "name", name)
    project.metadata = {
        **project.metadata,
        "project_name_format": 2,
        "project_name_base": base,
        "project_name_generated": name,
    }


def migrate_automatic_name(project: Project) -> None:
    if project.metadata.get("project_name_format") == 2 or not has_automatic_name(project):
        return
    # Preserve an existing collision ordinal without guessing whether a name
    # is automatic from its shape. The explicit flags above establish that.
    old_base = (
        f"{project.flight_date.isoformat()}_"
        f"{project.departure_airport_id}-{project.destination_airport_id}"
    )
    match = re.fullmatch(re.escape(old_base) + r"(_[2-9]\d*|_1\d+)?", project.name)
    suffix = (match.group(1) or "") if match else ""
    refresh_automatic_name(project)
    if suffix:
        name = f"{project.name[:60 - len(suffix)]}{suffix}"
        object.__setattr__(project, "name", name)
        project.metadata["project_name_generated"] = name
