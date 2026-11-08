"""MSM-only backport of the upstream Forecast selection regression cases."""

import pytest

from autonavlog.application.calculation_service import CalculationService
from autonavlog.domain.weather import ForecastCoverageError
from autonavlog.weather.fake_provider import FakeWeatherProvider
from autonavlog.weather.forecast_provider import ForecastWeatherProvider

OLD, NEW = "20260728000000", "20260728030000"


class Candidates(FakeWeatherProvider):
    def __init__(self, model, *, exclude=lambda run, req: False, fail=None):
        super().__init__(runs=(NEW, OLD))
        self.model, self.exclude, self.fail = model, exclude, fail
        self.checked = []

    def candidate_runs(self, requirement):
        return self.runs

    def check_run(self, run, requirement):
        self.checked.append((run, requirement))
        if self.fail:
            raise RuntimeError(self.fail)
        if self.exclude(run, requirement):
            raise ForecastCoverageError(("ALTITUDE_OUTSIDE_HGT_RANGE",))
        self.prepare_run(run, requirement)

    def query_batch(self, run, requests):
        return [r.model_copy(update={"metadata": {"model": self.model, "forecast_run_id": run}})
                for r in super().query_batch(run, requests)]


def _local_forecast_session():
    from pathlib import Path

    from test_local_calculation import calculate

    from autonavlog.local import LocalApplication

    root = Path(__file__).resolve().parents[2]
    local = LocalApplication(root / "data", forecast_fixture=root / "tests/fixtures/msm")
    msm, gsm = Candidates("MSM"), None
    local.session.weather_provider = ForecastWeatherProvider({"MSM": msm})
    calculate(local, forecast=True)
    return local, msm, gsm


def test_facade_input_change_pins_success_then_unchanged_action_refreshes():
    import json

    local, msm, gsm = _local_forecast_session()
    try:
        local.session.project.selected_forecast_run_id = OLD
        local.session.last_calculation = None
        first = json.loads(local.dispatch("calculate"))
        assert first["outcome"]["selected_forecast_run_id"] == OLD
        local.session.project.descent_rate_fpm = 1000
        assert not local.app.forecast_refresh_requested(local.session, local.session.project)
        changed = json.loads(local.dispatch("calculate"))
        assert changed["outcome"]["selected_forecast_run_id"] == OLD
        assert local.app.forecast_refresh_requested(local.session, local.session.project)
        second = json.loads(local.dispatch("calculate"))
        assert second["outcome"]["selected_forecast_run_id"] == NEW
    finally:
        local.close()


def test_facade_update_wait_and_processing_preserve_last_good():
    import json

    local, msm, gsm = _local_forecast_session()
    try:
        assert local.session.last_calculation is not None
        last = local.session.last_calculation.model_dump(mode="json")
        local.session.project.selected_forecast_run_id = OLD
        local.session.project.descent_rate_fpm = 1000
        msm.exclude = lambda run, req: run == OLD
        result = json.loads(local.dispatch("calculate"))
        assert "FORECAST_UPDATE_REQUIRED" in [i["code"] for i in result["outcome"]["issues"]]
        assert local.session.last_calculation.model_dump(mode="json") == last
        msm.fail = "decode failure"
        json.loads(local.dispatch("calculate"))
        assert local.session.last_calculation.model_dump(mode="json") == last
    finally:
        local.close()


def test_final_requirement_with_other_msm_waits_without_adopting_partial_results(
    airports, performance_repository, project,
):
    project.selected_forecast_run_id = OLD
    msm = Candidates("MSM")
    msm.exclude = lambda run, req: run == OLD and bool(msm.query_history)
    service = CalculationService(airports, performance_repository)
    result = service.calculate(project, ForecastWeatherProvider({"MSM": msm}))
    assert not result.sections
    assert "FORECAST_UPDATE_REQUIRED" in [i.code for i in result.blockers]
    assert result.selected_forecast_run_id == OLD



@pytest.mark.parametrize("unavailable", [False, True])
def test_final_selection_failure_does_not_invent_run_coverage_error(
    airports, performance_repository, project, monkeypatch, unavailable,
):
    import autonavlog.application.calculation_service as module
    from autonavlog.application.forecast_selection import ForecastUnavailable

    original = module.select_forecast
    calls = 0

    def selection(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            if unavailable:
                raise ForecastUnavailable(("NO_SPEC_COMPATIBLE_RUN",))
            raise RuntimeError("final decode failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "select_forecast", selection)
    result = CalculationService(airports, performance_repository).calculate(
        project, ForecastWeatherProvider({"MSM": Candidates("MSM")})
    )
    assert calls == 2
    assert [issue.code for issue in result.blockers] == [
        "FORECAST_UNAVAILABLE" if unavailable else "FORECAST_PREPARE_FAILED",
    ]

