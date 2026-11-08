"""The same synchronous application action resumes at the portable IO boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autonavlog.local import LocalApplication
from scripts.local_reference import reference_state

ROOT = Path(__file__).resolve().parents[2]
FEED = ROOT / "tests/fixtures/msm-portable"


def catalog_text(feed=FEED):
    catalog = json.loads((feed / "catalog.json").read_text())
    now = datetime.now(UTC)
    catalog.update(generated_at=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat())
    return json.dumps(catalog)


@pytest.fixture
def local():
    application = LocalApplication(ROOT / "data")
    state = reference_state(feed=str(FEED))
    application.dispatch("bootstrap", state["workingRecovery"])
    yield application
    application.close()


def resume(local, requests, feeds=None):
    for _ in range(20):
        response = json.loads(local.dispatch_response("calculate"))
        if "weather_request" not in response:
            return response
        request = response["weather_request"]
        requests.append(request)
        model = request["model"]
        if feeds is None:
            assert model == "MSM"
        feed = FEED if feeds is None else feeds[model]
        if request["kind"] == "catalog":
            assert local.weather_catalog(model, catalog_text(feed)) == "{}"
        else:
            asset = request["asset"]
            assert local.accept_weather(model, (feed / asset["file"]).read_bytes(),
                                        asset["sha256"]) == "{}"
    pytest.fail("portable IO replay failed to converge")


def test_msm_calculation_resumes_without_gsm_or_publishing_partial_result(local, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("native IO"))
    before = local.session.last_calculation
    local.begin_weather()
    suspended = json.loads(local.dispatch_response("calculate"))
    assert suspended["weather_request"] == {"model": "MSM", "kind": "catalog", "asset": None}
    assert local.session.last_calculation is before
    requests = []
    state = resume(local, requests)
    assert "error" not in state
    assert state["outcome"]["status"] == "READY_FOR_COPY"
    assert [r["kind"] for r in requests] == ["catalog", "prepared"]
    assert set(local.local_weather.clients) == {"MSM"}
    local.begin_weather()
    assert not local.local_weather.clients["MSM"].payloads
    assert "weather_request" in json.loads(local.dispatch_response("calculate"))

