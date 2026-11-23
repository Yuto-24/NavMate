"""Published coordinates and legacy identities remain traceable to their original inputs."""
import io
import json
import runpy
from pathlib import Path
from zipfile import ZipFile

import shapefile

from autonavlog.domain.project import AipReferencePointSource, ReferencePointSnapshot

ROOT = Path(__file__).resolve().parents[2]


def test_vrep_scope_provenance_and_published_coordinates():
    points = json.loads((ROOT / "data/reference/vrep.json").read_text())
    assert len(points) == len({point["reference_id"] for point in points}) == 528
    archive_path = ROOT / "data/reference/aip/20261029/sources/Shapefile_20261029.zip"
    stem = "Shapefile_20261029/Visual_REP_EFF20261029"
    with ZipFile(archive_path) as archive, shapefile.Reader(
        **{ext: io.BytesIO(archive.read(stem + "." + ext)) for ext in ("shp", "shx", "dbf")},
        encoding="utf-8",
    ) as reader:
        for index, (point, row) in enumerate(zip(points, reader.iterShapeRecords(), strict=True)):
            snapshot = ReferencePointSnapshot.model_validate(point)
            assert isinstance(snapshot.source, AipReferencePointSource)
            assert snapshot.source.record_index == index
            assert snapshot.source.airport_designators == row.record["AD"]
            assert snapshot.source.effective_date.isoformat() == "2026-10-29"
            assert (snapshot.longitude_deg, snapshot.latitude_deg) == tuple(row.shape.points[0])
            assert snapshot.name == row.record["CS"]
            assert snapshot.name_ja == row.record["CS_JP"]
    shared = [p for p in points if p["source"]["airport_designators"] == "RJFU / RJDU"]
    assert len(shared) == 10
    assert all(p["reference_id"].startswith("RJFU-VREP-") for p in shared)


def test_committed_catalog_and_legacy_matches_are_reproducible():
    generator = runpy.run_path(str(ROOT / "scripts/reference/build_vrep_catalog.py"))
    committed = json.loads((ROOT / "data/reference/vrep.json").read_text())
    assert committed == generator["catalog"]()
    legacy = generator["legacy_catalog"]()
    matches = json.loads((ROOT / "data/reference/vrep_legacy_matches.json").read_text())
    assert len(matches) == len(legacy) == 115
    assert set(matches) <= {p["reference_id"] for p in committed}
    # Model round-trip must preserve the exact match digest used during explicit open.
    assert matches == {
        p["reference_id"]: generator["snapshot_digest"](
            ReferencePointSnapshot.model_validate(p).model_dump(mode="json")
        ) for p in legacy
    }
