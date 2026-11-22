"""Check KML against saved projections and write the dated acceptance manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

NS = {"k": "http://www.opengis.net/kml/2.2"}
CASES = {
    "general-ftd": (7500, 2500, 300, 60),
    "rjfm-return-500": (4500, 1500, 360, 0),
    "rjfm-return-1000": (4500, 1500, 180, 0),
}


def check_coordinates(element: ET.Element, expected: list[tuple[float, float, float]]) -> None:
    text = element.findtext("k:coordinates", namespaces=NS)
    assert text
    actual = [tuple(map(float, point.split(","))) for point in text.split()]
    assert len(actual) == len(expected)
    for point, wanted in zip(actual, expected, strict=True):
        assert len(point) == 3
        assert all(math.isfinite(value) for value in point)
        assert all(abs(a - b) < 1e-8 for a, b in zip(point, wanted, strict=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("source_sha")
    args = parser.parse_args()
    assert re.fullmatch(r"[0-9a-f]{40}", args.source_sha)
    records = {}
    for name, (start, target, vertical, deceleration) in CASES.items():
        profile = json.loads((args.directory / f"{name}.profile.json").read_text())
        root = ET.parse(args.directory / f"{name}.kml").getroot()
        lines = root.findall(".//k:LineString", NS)
        assert len(lines) == len(profile["segments"])
        for line, segment in zip(lines, profile["segments"], strict=True):
            assert line.findtext("k:altitudeMode", namespaces=NS) == "absolute"
            check_coordinates(line, [
                (p["longitude_deg"], p["latitude_deg"], p["altitude_ft_msl"] * 0.3048)
                for p in segment["points"]
            ])
        markers = [m for m in profile["markers"] if m["kind"] != "CHECK_POINT"]
        markers += [m for m in profile["markers"] if m["kind"] == "CHECK_POINT"]
        points = root.findall(".//k:Point", NS)
        assert len(points) == len(markers)
        for point, marker in zip(points, markers, strict=True):
            ground = marker["kind"] == "CHECK_POINT"
            assert point.findtext("k:altitudeMode", namespaces=NS) == (
                "clampToGround" if ground else "absolute"
            )
            p = marker["point"]
            check_coordinates(point, [
                (marker["reference_longitude_deg"], marker["reference_latitude_deg"], 0)
                if ground else (
                    p["longitude_deg"], p["latitude_deg"], p["altitude_ft_msl"] * 0.3048,
                )
            ])
        descent = [s for s in profile["segments"] if s["phase"] == "DESCENT"]
        first, last = descent[0]["points"][0], descent[-1]["points"][-1]
        assert abs(first["altitude_ft_msl"] - start) < 1e-6
        assert abs(last["altitude_ft_msl"] - target) < 1e-6
        assert abs(
            last["elapsed_seconds"] - first["elapsed_seconds"] - vertical - deceleration
        ) < 1e-6
        level = next(
            m["point"] for m in markers if m["kind"] == "LEVEL_OFF"
            and abs(m["point"]["elapsed_seconds"] - first["elapsed_seconds"] - vertical) < 1e-6
        )
        assert abs(last["elapsed_seconds"] - level["elapsed_seconds"] - deceleration) < 1e-6
        assert {"CLIMB", "CRUISE", "DESCENT", "VISUAL_ARRIVAL"} == {
            s["phase"] for s in profile["segments"]
        }
        assert {"RCA", "EOC", "LEVEL_OFF"} <= {m["kind"] for m in markers}
        if name == "general-ftd":
            assert any(m["kind"] == "CHECK_POINT" for m in markers)
        else:
            assert (first["latitude_deg"], first["longitude_deg"]) == (
                31.985137767624444, 131.42429852046251,
            )
            arita = next(m["point"] for m in markers if m["name"] == "ARITA")
            assert last == arita
        records[name] = {
            "start_altitude_ft_msl": start, "target_altitude_ft_msl": target,
            "vertical_seconds": vertical, "deceleration_seconds": deceleration,
            "eoc": first, "level_off": level, "descent_end": last,
            "arrival_end": profile["segments"][-1]["points"][-1],
            "ground_check_points": [m for m in markers if m["kind"] == "CHECK_POINT"],
            "kml_structure_and_coordinates": "passed",
        }
    with ZipFile(args.directory / "sources.zip", "w", ZIP_DEFLATED) as archive:
        for name in CASES:
            for suffix in ("last-calculation", "profile"):
                path = args.directory / f"{name}.{suffix}.json"
                archive.write(path, path.name)
    files = [args.directory / "sources.zip", *(args.directory / f"{name}.kml" for name in CASES)]
    manifest = {
        "source_sha": args.source_sha, "generated_date_jst": "2026-11-23",
        "google_earth_visual_acceptance": "NOT_VERIFIED", "issue_173": "KEEP_OPEN",
        "input_provenance": {
            "general-ftd": "scripts.local_reference.reference_state(local=True, manual=True)",
            "rjfm-return": (
                "generate.py: return_state(500/1000); "
                "tests/fixtures/issue_117_ftd.json FTD weather"
            ),
            "snapshot_archive": "sources.zip: saved Last Calculation and common profile per case",
        },
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "expected": records,
    }
    (args.directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


if __name__ == "__main__":
    main()
