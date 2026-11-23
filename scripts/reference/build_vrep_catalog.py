"""Use published AIP geometry; retain exact legacy identities for verified upgrades."""

import hashlib
import io
import json
import re
from pathlib import Path
from zipfile import ZipFile

import shapefile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/reference/vrep-169-confirmed-source.md"
TARGET = ROOT / "data/reference/vrep.json"
URL = "https://github.com/Yuto-24/AutoNavLog/issues/169#issuecomment-6415872164"


def legacy_catalog():
    points = []
    for block in re.split(r"^## ", SOURCE.read_text(), flags=re.M)[1:]:
        airport = block[:4]
        if not re.match(r"RJ[A-Z]{2}", airport) or airport == "RJFY":
            continue
        filename = re.search(r"資料 `([^`]+)`", block)[1]
        sha = re.search(r"SHA-256 `([^`]+)`", block)[1]
        table = re.search(r"表: PDF p(\d+), (.*?), EFF ([\d-]+)", block)
        arp = re.search(r"ARP: PDF p(\d+), EFF ([\d-]+), (\d+N) (\d+E)", block)
        lat, lon = map(float, re.search(r"ARP十進度: ([\d.]+), ([\d.]+)", block).groups())
        for line in block.splitlines():
            if not line.startswith(f"|{airport}-VREP-"):
                continue
            pid, name, japanese, bearing, distance, latitude, longitude, note = line[1:-1].split(
                "|"
            )
            points.append(
                dict(
                    reference_id=pid,
                    name=name,
                    name_ja=japanese,
                    kind="VISUAL_REPORTING_POINT",
                    airport_icao=airport,
                    latitude_deg=float(latitude),
                    longitude_deg=float(longitude),
                    bearing_true_deg=float(bearing),
                    distance_nm=float(distance),
                    note=note,
                    derivation=(
                        "Geodesic.WGS84.Direct(arp_latitude_deg, arp_longitude_deg, "
                        "bearing_true_deg, distance_nm * 1852); lat2/lon2 rounded to 6 decimals; "
                        "no magnetic variation"
                    ),
                    source=dict(
                        url=URL,
                        filename=filename,
                        sha256=sha,
                        table_pdf_page=int(table[1]),
                        table_page=table[2],
                        table_effective_date=table[3],
                        arp_pdf_page=int(arp[1]),
                        arp_effective_date=arp[2],
                        arp_latitude_dms=arp[3],
                        arp_longitude_dms=arp[4],
                        arp_latitude_deg=lat,
                        arp_longitude_deg=lon,
                    ),
                )
            )
    assert len(points) == len({p["reference_id"] for p in points}) == 115
    assert len({p["airport_icao"] for p in points}) == 16
    return points


DATASET = ROOT / "data/reference/aip/20261029"
MATCHES = ROOT / "data/reference/vrep_legacy_matches.json"


def snapshot_digest(point):
    return hashlib.sha256(
        json.dumps(point, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def catalog():
    manifest = json.loads((DATASET / "source_manifest.json").read_text())
    source = next(a for a in manifest["source_archives"] if a["filename"].startswith("Shapefile_"))
    archive_path = DATASET / "sources" / source["filename"]
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == source["sha256"]
    def normalize(name):
        return re.sub(r"[^A-Z0-9]", "", name.upper())
    legacy = {(p["airport_icao"], normalize(p["name"])): p for p in legacy_catalog()}
    points = []
    matched = set()
    stem = "Shapefile_20261029/Visual_REP_EFF20261029"
    with ZipFile(archive_path) as archive:
        with shapefile.Reader(
            **{ext: io.BytesIO(archive.read(stem + "." + ext)) for ext in ("shp", "shx", "dbf")},
            encoding="utf-8",
        ) as reader:
            for index, row in enumerate(reader.iterShapeRecords()):
                raw = row.record.as_dict()
                airports = raw["AD"].split(" / ")
                assert all(re.fullmatch(r"[A-Z]{4}", airport) for airport in airports)
                candidates = [legacy[key] for airport in airports
                              if (key := (airport, normalize(raw["CS"]))) in legacy]
                assert len(candidates) <= 1
                reference_id = (candidates[0]["reference_id"] if candidates
                                else f"AIP20261029-VREP-{index}")
                if candidates:
                    assert reference_id not in matched
                    matched.add(reference_id)
                assert row.shape.shapeType == shapefile.POINT and len(row.shape.points) == 1
                longitude, latitude = row.shape.points[0]
                assert re.fullmatch(r"[0-9.]+°T", raw["BRG"])
                assert re.fullmatch(r"[0-9.]+NM", raw["DIST"])
                points.append(dict(
                    reference_id=reference_id, name=raw["CS"], name_ja=raw["CS_JP"],
                    kind="VISUAL_REPORTING_POINT", airport_icao=airports[0],
                    latitude_deg=latitude, longitude_deg=longitude,
                    bearing_true_deg=float(raw["BRG"][:-2]), distance_nm=float(raw["DIST"][:-2]),
                    note=" / ".join(
                        raw[key] for key in ("REMARKS1", "REMARKS2", "REMARKS3") if raw[key]
                    ),
                    derivation="Published WGS84 coordinates from AIP Visual_REP Shapefile",
                    source=dict(
                        format="AIP_SHAPEFILE", url="https://top.swim.mlit.go.jp/swim/",
                        filename=source["filename"], sha256=source["sha256"],
                        dataset_id=manifest["dataset_id"], layer_id="Visual_REP",
                        record_index=index, effective_date=manifest["effective_date"],
                        airport_designators=raw["AD"],
                    ),
                ))
    assert len(points) == len({p["reference_id"] for p in points}) == 528
    assert len(matched) == len(legacy) == 115
    return points


if __name__ == "__main__":
    TARGET.write_text(json.dumps(catalog(), ensure_ascii=False, indent=2) + "\n")
    MATCHES.write_text(json.dumps(
        {p["reference_id"]: snapshot_digest(p) for p in legacy_catalog()},
        ensure_ascii=False, indent=2, sort_keys=True,
    ) + "\n")
