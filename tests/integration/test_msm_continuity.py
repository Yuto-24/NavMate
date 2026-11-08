"""Issue #356: usable Local data survives catalog expiry, with explicit refresh boundaries."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from test_local_forecast import FEED, ROOT, catalog_text
from test_local_forecast import local as local


def calculate(local, catalogs, failures=None, payloads=None):
    local.begin_weather()
    for catalog, current in catalogs:
        assert local.weather_catalog("MSM", json.dumps(catalog), current=current) == "{}"
    requested = []
    for _ in range(32):
        result = json.loads(local.dispatch_response("calculate"))
        if "weather_request" not in result:
            return result, requested
        request = result["weather_request"]
        assert request["model"] == "MSM" and request["kind"] == "prepared"
        asset = request["asset"]
        requested.append(asset["run"])
        code = (failures or {}).get(asset["run"])
        if code:
            local.weather_failed("MSM", asset["sha256"], code, code)
        else:
            data = (payloads or {}).get(asset["sha256"])
            if data is None:
                data = (FEED / asset["file"]).read_bytes()
            error = json.loads(local.accept_weather("MSM", data, asset["sha256"]))
            if error:
                local.weather_failed("MSM", asset["sha256"], **error["error"])
    pytest.fail("acquisition did not converge")


def test_expired_catalog_and_cache_only_data_calculate_without_claiming_latest(local):
    catalog = json.loads(catalog_text())
    catalog.update(generated_at="2026-09-16T00:00:00Z", expires_at="2026-09-16T06:00:00Z")
    original = dict(catalog)
    state, _ = calculate(local, [(catalog, False)])
    assert state["readiness"]["calculationIsCurrent"]
    assert state["outcome"]["selected_forecast_run_id"] == "20260915210000"
    metadata = state["workingRecovery"]["last_calculation"]["forecast_metadata"]
    assert metadata["latest_complete_msm_run_id"] is None
    assert not any(i["code"] in {"FORECAST_STALE_RUN", "FORECAST_BACKUP_USED"}
                   for i in state["outcome"]["issues"])
    assert catalog == original


@pytest.mark.parametrize("current", [False, True])
def test_missing_daily_listing_uses_verified_run_without_claiming_latest(local, current):
    catalog = json.loads(catalog_text())
    catalog["listings"].pop(next(url for url in catalog["listings"] if url.endswith("/09/16")))
    if not current:
        catalog.update(generated_at="2026-09-15T00:00:00Z", expires_at="2026-09-15T06:00:00Z")
    original = json.dumps(catalog, sort_keys=True)
    state, requested = calculate(local, [(catalog, current)])
    assert state["readiness"]["calculationIsCurrent"]
    assert requested == ["20260915210000"]
    assert state["workingRecovery"]["last_calculation"]["forecast_metadata"][
        "latest_complete_msm_run_id"] is None
    assert json.dumps(catalog, sort_keys=True) == original


@pytest.mark.parametrize("failure", ["values", "altitude", "time", "integrity", "identity",
                                   "pinned", "all_listings"])
def test_missing_daily_listing_does_not_accept_unusable_data_or_replace_last_good(local, failure):
    catalog = json.loads(catalog_text())
    catalog["listings"].pop(next(url for url in catalog["listings"] if url.endswith("/09/16")))
    before = local.session.last_calculation.model_dump(mode="json")
    failures, payloads = {}, {}
    if failure == "values":
        feed = ROOT / "tests/fixtures/forecast-policy/msm-source-unavailable"
        catalog["assets"] = json.loads(catalog_text(feed))["assets"]
        payloads = {a["sha256"]: (feed / a["file"]).read_bytes() for a in catalog["assets"]}
    elif failure == "time":
        local.session.project.planned_departure_time_jst += timedelta(hours=11)
    elif failure == "altitude":
        from jma_gpv_weather import MsmPreparedData

        for asset in catalog["assets"]:
            data = MsmPreparedData.from_bytes((FEED / asset["file"]).read_bytes())
            pressure = {key: value for key, value in data.pressure.items() if key[1] >= 950}
            payload = MsmPreparedData(
                data.selection, data.surface, pressure, data.source_hashes,
            ).to_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            asset.update(file=f"{digest}.npz", sha256=digest, bytes=len(payload))
            payloads[digest] = payload
    elif failure == "integrity":
        payloads = {a["sha256"]: b"corrupt" for a in catalog["assets"]}
    elif failure == "identity":
        catalog["listings"] = {url: body.replace("Lsurf_FH00-15", "Lsurf_FH00-16")
                               for url, body in catalog["listings"].items()}
    elif failure == "pinned":
        local.session.project.descent_rate_fpm = 1000
        catalog["assets"] = catalog["assets"][1:]
    else:
        catalog["listings"] = {}
    state, _ = calculate(local, [(catalog, False)], failures, payloads)
    assert "error" in state or state["outcome"]["status"] != "READY_FOR_COPY"
    assert local.session.last_calculation.model_dump(mode="json") == before


@pytest.mark.parametrize("failure", ["missing_asset", "WEATHER_SOURCE_UNAVAILABLE",
                                   "WEATHER_PAYLOAD_INTEGRITY_FAILED", "corrupt_bytes",
                                   "SOURCE_VALUE_UNAVAILABLE"])
def test_refresh_uses_newest_healthy_msm_before_backup(local, failure):
    catalog = json.loads(catalog_text())
    failures, payloads = {}, {}
    newest = catalog["assets"][0]
    if failure == "missing_asset":
        catalog["assets"] = catalog["assets"][1:]
    elif failure == "corrupt_bytes":
        payloads[newest["sha256"]] = b"corrupt"
    elif failure == "SOURCE_VALUE_UNAVAILABLE":
        feed = ROOT / "tests/fixtures/forecast-policy/msm-source-unavailable"
        invalid = json.loads(catalog_text(feed))["assets"][0]
        catalog["assets"][0] = invalid
        payloads[invalid["sha256"]] = (feed / invalid["file"]).read_bytes()
    else:
        failures[newest["run"]] = failure
    state, _ = calculate(local, [(catalog, True)], failures, payloads)
    assert state["readiness"]["calculationIsCurrent"]
    assert state["outcome"]["selected_forecast_run_id"] == "20260915180000"
    last = state["workingRecovery"]["last_calculation"]
    assert last["project"]["selected_forecast_run_id"] == "20260915180000"
    assert last["forecast_metadata"]["forecast_run_id"] == "20260915180000"
    assert set(local.local_weather.clients) == {"MSM"}


def test_changed_inputs_never_replace_missing_pinned_run_and_keep_last_good(local):
    catalog = json.loads(catalog_text())
    old_only = dict(catalog, assets=catalog["assets"][1:])
    first, _ = calculate(local, [(old_only, True)])
    last = first["workingRecovery"]["last_calculation"]
    local.session.project.sections[0].planned_altitude_ft_msl += 500
    newest_only = dict(catalog, assets=catalog["assets"][:1])
    failed, requested = calculate(local, [(newest_only, True)])
    assert failed["error"]["code"] == "WEATHER_PREPARED_UNAVAILABLE"
    assert requested == []
    assert local.session.last_calculation.model_dump(mode="json") == last


def test_corruption_is_not_reclassified_as_missing_older_delivery(local):
    catalog = json.loads(catalog_text())
    before = local.session.last_calculation.model_dump(mode="json")
    state, _ = calculate(local, [(catalog, True)], {
        asset["run"]: "WEATHER_PAYLOAD_INTEGRITY_FAILED" for asset in catalog["assets"]
    })
    assert state["error"]["code"] == "WEATHER_PAYLOAD_INTEGRITY_FAILED"
    assert local.session.last_calculation.model_dump(mode="json") == before


def test_new_catalog_missing_delivery_can_use_retained_catalog(local):
    cached = json.loads(catalog_text())
    cached["assets"] = cached["assets"][1:]
    server = json.loads(catalog_text())
    server["assets"] = server["assets"][:1]
    state, _ = calculate(local, [(server, True), (cached, False)], {
        "20260915210000": "WEATHER_SOURCE_UNAVAILABLE",
    })
    assert state["readiness"]["calculationIsCurrent"]
    assert state["outcome"]["selected_forecast_run_id"] == "20260915180000"
    metadata = state["workingRecovery"]["last_calculation"]["forecast_metadata"]
    assert metadata["latest_complete_msm_run_id"] is None


@pytest.mark.parametrize("changed_inputs", [False, True])
def test_value_failure_tries_healthy_cached_payload_of_same_run(local, changed_inputs):
    feed = ROOT / "tests/fixtures/forecast-policy/msm-source-unavailable"
    server = json.loads(catalog_text(feed))
    cached = json.loads(catalog_text())
    cached["generated_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    if changed_inputs:
        local.session.project.descent_rate_fpm = 1000
    payloads = {asset["sha256"]: (feed / asset["file"]).read_bytes()
                for asset in server["assets"]}
    state, requested = calculate(local, [(server, True), (cached, False)], payloads=payloads)
    assert state["readiness"]["calculationIsCurrent"]
    assert state["outcome"]["selected_forecast_run_id"] == "20260915210000"
    assert requested == ["20260915210000", "20260915210000"]
    assert set(local.local_weather.clients) == {"MSM"}


def test_final_requirement_does_not_keep_confirmation_from_an_incomplete_current_asset():
    from jma_gpv_weather import MsmPreparedData

    from autonavlog.domain.weather import ForecastRequirement
    from autonavlog.weather.local_forecast import LocalForecastWeather

    server = json.loads(catalog_text())
    cached = json.loads(catalog_text())
    cached["generated_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    asset = cached["assets"][0]
    full_payload = (FEED / asset["file"]).read_bytes()
    data = MsmPreparedData.from_bytes(full_payload)
    partial_payload = MsmPreparedData(
        data.selection, {}, data.pressure, data.source_hashes,
    ).to_bytes()
    digest = hashlib.sha256(partial_payload).hexdigest()
    server["assets"] = [
        dict(asset, file=f"{digest}.npz", sha256=digest, bytes=len(partial_payload)),
    ]
    cached["assets"] = [asset]
    weather = LocalForecastWeather()
    weather.catalog("MSM", json.dumps(server))
    weather.catalog("MSM", json.dumps(cached), current=False)
    weather.accept("MSM", partial_payload, digest)
    weather.accept("MSM", full_payload, asset["sha256"])
    provider = weather.provider.models["MSM"]
    initial = ForecastRequirement(valid_times_utc=(datetime(2026, 9, 16, 4, 30, tzinfo=UTC),))
    provider.check_run(asset["run"], initial)
    assert provider.latest_run_confirmed(asset["run"])

    final = initial.model_copy(update={"require_surface_temperature": True})
    provider.check_run(asset["run"], final)
    assert weather.clients["MSM"].prepared_assets[asset["run"]] == asset["sha256"]
    assert not provider.latest_run_confirmed(asset["run"])


@pytest.mark.parametrize("hours,current,expected", [
    (0, True, False), (3, True, False), (6, True, False), (9, True, True),
    (12, True, True), (12, False, False),
])
def test_advisory_requires_verified_latest_and_three_run_intervals(hours, current, expected):
    from test_forecast_calculation import NEW, _local_forecast_session

    application, msm, _ = _local_forecast_session()
    try:
        old = (datetime.strptime(NEW, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
               - timedelta(hours=hours)).strftime("%Y%m%d%H%M%S")
        msm.runs = tuple(dict.fromkeys((NEW, old)))
        msm.latest_run_confirmed = lambda run: current
        application.session.project.selected_forecast_run_id = old
        application.session.last_calculation = None
        state = json.loads(application.dispatch("calculate"))
        advisory = [i for i in state["outcome"]["issues"] if i["code"] == "FORECAST_STALE_RUN"]
        assert bool(advisory) is expected
        assert state["readiness"]["calculationIsCurrent"]
        if expected:
            proof = advisory[0]["metadata"]
            assert proof["selected_run_id"] == old
            assert proof["latest_complete_msm_run_id"] == NEW
            assert proof["run_steps_behind"] == hours // 3
            assert proof["checked_at"]
            recovery = state["workingRecovery"]
            restored = json.loads(application.dispatch("bootstrap", recovery))
            assert advisory[0] in restored["outcome"]["issues"]
            # Changed inputs pin the old Run. Unknown latest retains original proof.
            application.session.project.descent_rate_fpm = 1000
            msm.latest_run_confirmed = lambda run: False
            offline = json.loads(application.dispatch("calculate"))
            assert advisory[0] in offline["outcome"]["issues"]
            saved_issues = offline["workingRecovery"]["last_calculation"]["outcome"]["issues"]
            assert advisory[0] in saved_issues
    finally:
        application.close()


def test_failed_final_requirement_does_not_add_an_advisory():
    from test_forecast_calculation import _local_forecast_session

    application, msm, _ = _local_forecast_session()
    try:
        old, new = "20260728000000", "20260728090000"
        msm.runs = (new, old)
        msm.exclude = lambda run, req: run == old and bool(req.coverage_requests)
        application.session.project.selected_forecast_run_id = old
        application.session.last_calculation = None
        state = json.loads(application.dispatch("calculate"))
        codes = {issue["code"] for issue in state["outcome"]["issues"]}
        assert "FORECAST_UPDATE_REQUIRED" in codes
        assert "FORECAST_STALE_RUN" not in codes
        assert application.session.last_calculation is None
    finally:
        application.close()
