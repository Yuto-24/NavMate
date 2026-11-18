from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import pytest

from autonavlog.local import LocalApplication
from autonavlog.weather.destination_taf import FakeDestinationWindProvider
from autonavlog.weather.fake_provider import FakeWeatherProvider

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "connected_oita_routes.kml"
ISSUE_129_FIXTURE = ROOT / "tests" / "fixtures" / "issue_129_omaru_point.kml"
ISSUE_129_SINGLE_LINE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "issue_129_single_line_omaru_point.kml"
)


def _connected_route_kml(vertex_count: int) -> str:
    start = (31.8771201986468, 131.4484514728637)
    end = (33.47949347092593, 131.7371201702322)
    coordinates = [
        (
            start[0] + (end[0] - start[0]) * index / (vertex_count - 1),
            start[1] + (end[1] - start[1]) * index / (vertex_count - 1),
        )
        for index in range(vertex_count)
    ]
    join_index = vertex_count // 2

    def coordinate_text(items: list[tuple[float, float]]) -> str:
        return " ".join(f"{longitude:.12f},{latitude:.12f}" for latitude, longitude in items)

    return f"""<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Doc</name>
    <Folder><name>Long route</name>
    <Placemark><name>RJFM</name><Point><coordinates>{start[1]},{start[0]}</coordinates>
    </Point></Placemark>
    <Placemark><name>A</name><LineString><coordinates>
    {coordinate_text(coordinates[: join_index + 1])}
    </coordinates></LineString></Placemark>
    <Placemark><name>B</name><LineString><coordinates>
    {coordinate_text(coordinates[join_index:])}
    </coordinates></LineString></Placemark>
    <Placemark><name>RJFO</name><Point><coordinates>{end[1]},{end[0]}</coordinates>
    </Point></Placemark>
    </Folder></Document></kml>"""


def _confirm_payload() -> dict[str, object]:
    return {
        "candidate_kind": "connected_lines",
        "candidate_index": 0,
        "route_use_confirmed": True,
        "flight_date": "2099-08-10",
        "departure_time_jst": "09:00",
        "total_usable_fuel_gal": 90,
        "default_variation_deg_east": 8,
        "all_leg_altitude_ft_msl": 3500,
        "defaults_confirmed": True,
    }


@pytest.fixture
def local():
    application = LocalApplication(ROOT / "data")
    # Keep the original calm-weather calculation inputs while exercising the Local boundary.
    application.session.weather_provider = FakeWeatherProvider(runs=("20990810000000",))
    application.app.destination_wind_provider = FakeDestinationWindProvider()
    yield application
    application.close()


def test_local_import_exposes_four_connected_candidates_and_records_selection(local) -> None:
    imported = json.loads(
        local.dispatch(
            "importRoute",
            {"filename": FIXTURE.name, "kml_text": FIXTURE.read_text(encoding="utf-8")},
        )
    )
    import_payload = imported["import"]
    candidates = import_payload["candidates"]
    assert import_payload["warnings"] == []
    assert [item["kind"] for item in candidates] == ["connected_lines"] * 4
    assert [item["index"] for item in candidates] == [0, 1, 2, 3]
    assert [item["name"] for item in candidates] == [
        "RJFM→RJFO①",
        "RJFM→RJFO②",
        "RJFO→RJFM①",
        "RJFO→RJFM②",
    ]
    assert [item["segmentCount"] for item in candidates] == [7, 6, 5, 5]
    assert [item["legCount"] for item in candidates] == [7, 6, 5, 5]
    assert [item["vertexCount"] for item in candidates] == [8, 7, 6, 6]
    assert [item["distanceNm"] for item in candidates] == [124.66, 151.42, 112.03, 129.01]
    assert candidates[0]["containerPath"] == ["大分経路", "RJFO", "RJFM→RJFO①"]
    assert candidates[0]["segmentNames"][0] == "RJFM→UMK(TC352,DIST6.5)"
    assert candidates[0]["segmentNames"][-1] == "杵築→RJFO(TC054,DIST6.5)"
    assert candidates[0]["maxJoinGapNm"] == pytest.approx(0.00061)
    confirmed = json.loads(local.dispatch("confirmRoute", _confirm_payload()))
    project = confirmed["project"]
    assert len(project["route_nodes"]) == 8
    assert project["route_nodes"][0]["name"] == "RJFM"
    assert project["route_nodes"][-1]["name"] == "RJFO"
    assert project["route_nodes"][1]["name"] == "変針点 UMK(MZE 004/6.2,NHT6.0)"
    assert project["route_nodes"][1]["name_source"] == "IMPORTED"
    assert project["route_nodes"][1]["source"] == "KML/KMZ Point"
    assert project["metadata"]["web_import_container_path"] == ["大分経路", "RJFO", "RJFM→RJFO①"]
    assert project["metadata"]["web_import_segment_names"] == candidates[0]["segmentNames"]


def test_connected_route_coordinate_limit_has_dedicated_error_and_allows_500(local) -> None:
    deduplicated_import = json.loads(
        local.dispatch(
            "importRoute",
            {
                "filename": "deduplicated.kml",
                "kml_text": """<kml xmlns="http://www.opengis.net/kml/2.2">
                <Document><name>Doc</name><Folder><name>Deduplicated</name>
                <Placemark><name>A</name><LineString><coordinates>
                131.448451472864,31.877120198647 131.448501472864,31.877120198647
                131.5,32.2 131.6,32.8
                </coordinates></LineString></Placemark>
                <Placemark><name>B</name><LineString><coordinates>
                131.6,32.8 131.737120170232,33.479493470926
                </coordinates></LineString></Placemark>
                </Folder></Document></kml>""",
            },
        )
    )
    deduplicated_candidate = deduplicated_import["import"]["candidates"][0]
    assert deduplicated_candidate["segmentCount"] == 2
    assert deduplicated_candidate["legCount"] == 3
    assert deduplicated_candidate["vertexCount"] == 4
    assert len(deduplicated_candidate["coordinates"]) == 4
    oversized_import = json.loads(
        local.dispatch(
            "importRoute", {"filename": "501.kml", "kml_text": _connected_route_kml(501)}
        )
    )
    oversized_candidate = oversized_import["import"]["candidates"][0]
    assert oversized_candidate["segmentCount"] == 2
    assert oversized_candidate["legCount"] == 500
    assert oversized_candidate["vertexCount"] == 501
    rejected = json.loads(local.dispatch_response("confirmRoute", _confirm_payload()))
    assert rejected["error"] == {
        "code": "ROUTE_COORDINATE_LIMIT_EXCEEDED",
        "message": (
            "選択した経路は座標数の上限（500点）を超えています。"
            "500点以下の経路を選択してください。"
        ),
        "details": {},
    }
    maximum_import = json.loads(
        local.dispatch(
            "importRoute", {"filename": "500.kml", "kml_text": _connected_route_kml(500)}
        )
    )
    maximum_candidate = maximum_import["import"]["candidates"][0]
    assert maximum_candidate["segmentCount"] == 2
    assert maximum_candidate["legCount"] == 499
    assert maximum_candidate["vertexCount"] == 500
    confirmed = json.loads(local.dispatch("confirmRoute", _confirm_payload()))
    assert len(confirmed["project"]["route_nodes"]) == 500


def test_invalid_group_falls_back_to_lines_and_points_only_remain_a_fallback(local) -> None:
    invalid = json.loads(
        local.dispatch(
            "importRoute",
            {
                "filename": "invalid.kml",
                "kml_text": """<kml xmlns="http://www.opengis.net/kml/2.2">
                <Document><name>Doc</name><Folder><name>Route</name>
                <Placemark><name>P1</name><Point><coordinates>131,31</coordinates>
                </Point></Placemark>
                <Placemark><name>P2</name><Point><coordinates>132,32</coordinates>
                </Point></Placemark>
                <Placemark><name>A</name><LineString><coordinates>131,31 131.1,31</coordinates>
                </LineString></Placemark>
                <Placemark><name>B</name><LineString><coordinates>132,32 132.1,32</coordinates>
                </LineString></Placemark>
                </Folder></Document></kml>""",
            },
        )
    )
    invalid_import = invalid["import"]
    assert [item["kind"] for item in invalid_import["candidates"]] == ["line", "line"]
    assert "結合せず個別の候補として保持しました" in invalid_import["warnings"][0]
    points_only = json.loads(
        local.dispatch(
            "importRoute",
            {
                "filename": "points.kml",
                "kml_text": """<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
                <Placemark><name>P1</name><Point><coordinates>131,31</coordinates>
                </Point></Placemark>
                <Placemark><name>P2</name><Point><coordinates>132,32</coordinates>
                </Point></Placemark>
                </Document></kml>""",
            },
        )
    )
    assert [item["kind"] for item in points_only["import"]["candidates"]] == ["points"]


def test_issue_129_explicit_omaru_point_is_one_imported_node_after_connected_confirmation(
    local,
) -> None:
    imported = json.loads(
        local.dispatch(
            "importRoute",
            {
                "filename": ISSUE_129_FIXTURE.name,
                "kml_text": ISSUE_129_FIXTURE.read_text(encoding="utf-8"),
            },
        )
    )
    candidate = imported["import"]["candidates"][0]
    assert candidate["kind"] == "connected_lines"
    assert candidate["coordinates"][2] == [32.16255070087476, 131.47036916946163]
    confirmed = json.loads(local.dispatch("confirmRoute", _confirm_payload()))
    nodes = confirmed["project"]["route_nodes"]
    assert [node["name"] for node in nodes] == ["RJFM", "UMK", "小丸", "RJFO"]
    assert [node["name"] for node in nodes].count("小丸") == 1
    assert all(node["name"] != "OMARU" for node in nodes)
    assert nodes[2]["name_source"] == "IMPORTED"
    assert (nodes[2]["latitude_deg"], nodes[2]["longitude_deg"]) == (
        32.16255070087476,
        131.47036916946163,
    )


def test_issue_129_omaru_display_name_does_not_change_calculated_leg_or_ttl_distance():
    def calculate_for(point_name: str) -> list[str]:
        with closing(LocalApplication(ROOT / "data")) as local:
            local.session.weather_provider = FakeWeatherProvider(runs=("20990810000000",))
            local.app.destination_wind_provider = FakeDestinationWindProvider()
            text = ISSUE_129_FIXTURE.read_text(encoding="utf-8").replace("小丸", point_name)
            local.dispatch("importRoute", {"filename": f"{point_name}.kml", "kml_text": text})
            local.dispatch("confirmRoute", _confirm_payload())
            state = json.loads(local.dispatch("calculate"))
            return [
                row["distance"]["text"]
                for row in state["outcome"]["display_rows"]
                if row["row_type"] == "PHYSICAL_LEG_SUMMARY"
            ]

    small_circle_distances = calculate_for("小丸")
    omaru_distances = calculate_for("OMARU")
    # The RJFM departure plan groups the imported route into two physical display legs.
    assert len(small_circle_distances) == 2
    assert small_circle_distances[-1].split(" / ")[1] == "97.5"
    assert small_circle_distances == omaru_distances


def test_issue_129_single_line_explicit_omaru_point_preserves_two_downstream_names(local) -> None:
    imported = json.loads(
        local.dispatch(
            "importRoute",
            {
                "filename": ISSUE_129_SINGLE_LINE_FIXTURE.name,
                "kml_text": ISSUE_129_SINGLE_LINE_FIXTURE.read_text(encoding="utf-8"),
            },
        )
    )
    assert imported["import"]["candidates"][0]["kind"] == "line"
    confirmed = json.loads(
        local.dispatch(
            "confirmRoute", {**_confirm_payload(), "candidate_kind": "line", "candidate_index": 0}
        )
    )
    nodes = confirmed["project"]["route_nodes"]
    assert [node["name"] for node in nodes] == ["RJFM", "UMK", "小丸", "日振島", "祝島", "RJFO"]
    assert nodes[2]["name_source"] == "IMPORTED"
    assert [(node["latitude_deg"], node["longitude_deg"]) for node in nodes[1:-1]] == [
        (31.985137767624444, 131.42429852046251),
        (32.16255070087476, 131.47036916946163),
        (33.18, 132.29),
        (33.3, 132.1),
    ]
