"""One-time upgrade of verified #169 snapshots to published Visual_REP coordinates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from autonavlog.domain.project import Project, ReferencePointSnapshot
from autonavlog.local_persistence import LocalProjectRecord


def refresh_legacy_references(
    record: LocalProjectRecord, reference_root: Path,
) -> LocalProjectRecord:
    """Prepare a validated copy; the caller commits it with its original token guard.

    Saved calculation inputs/results are historical evidence and are never migrated.
    Reading/listing/sync validation does not invoke this explicit-open operation.
    """
    expected = json.loads((reference_root / "vrep_legacy_matches.json").read_text())
    catalog = {
        raw["reference_id"]: ReferencePointSnapshot.model_validate(raw)
        for raw in json.loads((reference_root / "vrep.json").read_text())
    }
    result = record.model_copy(deep=True)
    now = datetime.now(UTC)

    def refresh(project: Project | None) -> bool:
        if project is None:
            return False
        changed = False
        for node in project.route_nodes:
            old = node.reference_snapshot
            if old is None or old.reference_id not in expected:
                continue
            digest = hashlib.sha256(json.dumps(
                old.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                ensure_ascii=False,
            ).encode()).hexdigest()
            if (
                digest != expected[old.reference_id]
                or node.source != f"REFERENCE:{old.reference_id}"
                or (node.latitude_deg, node.longitude_deg) != (old.latitude_deg, old.longitude_deg)
            ):
                continue
            current = catalog[old.reference_id]
            node.reference_snapshot = current.model_copy(deep=True)
            node.latitude_deg = current.latitude_deg
            node.longitude_deg = current.longitude_deg
            changed = True
        if changed:
            project.updated_at = now
        return changed

    draft_changed = refresh(result.draft)
    checkpoint_changed = refresh(result.checkpoint)
    if draft_changed or checkpoint_changed:
        result.token = uuid4()
        result.updatedAt = now
    return result
