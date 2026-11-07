"""Imported occurrence labels survive MAP confirmation and Project recovery."""

import base64
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from autonavlog.local import LocalApplication

ROOT = Path(__file__).resolve().parents[2]
CONFIRM = json.loads((ROOT / "tests/fixtures/issue_117_ftd.json").read_text())["confirm"]


@pytest.mark.parametrize("kmz", [False, True])
@pytest.mark.parametrize("connected", [False, True])
def test_rjfm_names_remain_bound_through_map_confirmation_edit_and_recovery(kmz, connected):
    text = (ROOT / "tests/fixtures/issue_129_omaru_point.kml").read_text()
    if not connected:
        text = """<kml><Document><name>route</name>
        <Placemark><name>小丸→日振島→祝島</name><LineString><coordinates>
        131.449,31.877 131.42429852046251,31.985137767624444
        131.47036916946163,32.16255070087476 132.29,33.18 131.99,33.78 131.737,33.479
        </coordinates></LineString></Placemark>
        <Placemark><name>小丸</name><Point><coordinates>
        131.47036916946163,32.16255070087476
        </coordinates></Point></Placemark></Document></kml>"""
    request = {"filename": "route.kml", "kml_text": text}
    if kmz:
        archive = io.BytesIO()
        with ZipFile(archive, "w") as output:
            output.writestr("doc.kml", text)
        request = {"filename": "route.kmz",
                   "content_base64": base64.b64encode(archive.getvalue()).decode()}
    app = LocalApplication(ROOT / "data")
    try:
        imported = json.loads(app.dispatch("importRoute", request))
        candidate = imported["import"]["candidates"][0]
        # The same import payload is reconstructed on a reload before adoption.
        recovered = json.loads(app.dispatch("bootstrap", imported["workingRecovery"]))
        assert recovered["import"]["candidates"] == imported["import"]["candidates"]
        names = ["UMK", "小丸"] if connected else [None, "小丸", "日振島", "祝島"]
        assert candidate["routeNames"][1:-1] == names
        points = [
            dict(name=name or f"WP{index}", name_source="IMPORTED" if name else "GENERATED",
                 latitude_deg=lat, longitude_deg=lon, airport_id=None)
            for index, ((lat, lon), name) in enumerate(zip(
                candidate["routeCoordinates"], candidate["routeNames"], strict=True,
            ))
        ]
        points[0]["airport_id"] = candidate["departureAirportId"]
        points[-1]["airport_id"] = candidate["destinationAirportId"]
        state = json.loads(app.dispatch("confirmRoute", {
            **CONFIRM, "candidate_kind": "map", "map_points": points,
        }))
        nodes = state["project"]["route_nodes"]
        expected = ["RJFM", "UMK", "小丸", *([] if connected else ["日振島", "祝島"]), "RJFO"]
        assert [node["name"] for node in nodes] == expected
        assert [[node["latitude_deg"], node["longitude_deg"]] for node in nodes[1:-1]] == (
            candidate["routeCoordinates"][1:-1]
        )
        assert len(nodes) == candidate["vertexCount"]
        omaru = nodes[2]
        assert omaru["name_source"] == "IMPORTED"
        renamed = json.loads(app.dispatch("renameRouteNode", {
            "node_id": omaru["id"], "name": "MY POINT",
        }))
        restored = json.loads(app.dispatch("bootstrap", renamed["workingRecovery"]))
        assert restored["project"] == renamed["project"]
        assert restored["project"]["route_nodes"][2]["name_source"] == "USER"
        assert restored["project"]["route_nodes"][2]["name"] == "MY POINT"
    finally:
        app.close()
