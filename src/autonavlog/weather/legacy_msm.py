"""Opt-in native MSM recovery; the portable/browser adapter is unchanged."""
from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Any

from autonavlog.domain.weather import ForecastRequirement, PreparedForecastRun
from autonavlog.weather.msm_adapter import MsmWeatherProvider


class LegacyMsmWeatherProvider(MsmWeatherProvider):
    def __init__(self, cache_dir: str | Path, client: Any | None = None):
        from jma_gpv_weather.msm.cached_client import CachedMsmClient

        super().__init__(cache_dir, client=client or CachedMsmClient(cache_dir=cache_dir))

    def begin_calculation(self) -> None:
        self._prepared.clear()
        self.client.begin_calculation()

    @property
    def acquisition_metadata(self) -> dict[str, Any]:
        return dict(self.client.acquisition_metadata)

    def prepare_run(
        self, forecast_run_id: str, requirement: ForecastRequirement,
    ) -> PreparedForecastRun:
        prepared = super().prepare_run(forecast_run_id, requirement)
        prepared.metadata["package_build"] = version("jma-gpv-weather")
        prepared.metadata.update(self.client.acquisition_metadata)
        return prepared
