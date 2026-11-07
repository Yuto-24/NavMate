"""Demand-driven browser transport for the upstream portable MSM/GSM clients.

A calculation may request a catalog or an exact Run payload and resume after the
Worker supplies it. Only the application policy selects models; the public library
owns discovery, payload validation, preparation and all meteorological decisions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jma_gpv_weather import GsmClient, MsmClient
from jma_gpv_weather.errors import (
    CacheIntegrityError,
    GsmCacheIntegrityError,
    GsmRunUnavailableError,
    MissingVariableError,
    NoCompatibleRunError,
    SelectedRunCoverageError,
)

from autonavlog.domain.weather import ForecastDataError, ForecastModel, ForecastRequirement
from autonavlog.weather.forecast_provider import ForecastWeatherProvider
from autonavlog.weather.gsm_adapter import GsmWeatherProvider
from autonavlog.weather.local_msm import (
    CATALOG_CLOCK_SKEW,
    LocalWeatherError,
    PreparedAsset,
    WeatherCatalog,
)
from autonavlog.weather.msm_adapter import MsmWeatherProvider


class LocalWeatherRequest(BaseException):
    """Suspend the synchronous calculation, without classifying it as a failure.

    Deliberately outside Exception: processing-error handlers must not convert a
    transport suspension into a completed calculation or consume refresh intent.
    Only LocalApplication's Worker boundary catches this signal.
    """

    def __init__(self, model: ForecastModel, asset: PreparedAsset | None = None) -> None:
        self.request = {
            "model": model,
            "kind": "catalog" if asset is None else "prepared",
            "asset": None if asset is None else asset.model_dump(mode="json"),
        }


class _PortableClient:
    model: ForecastModel

    def __init__(self) -> None:
        super().__init__()
        self.catalog: WeatherCatalog | None = None
        self.catalogs: list[WeatherCatalog] = []
        self.current_catalog: WeatherCatalog | None = None
        self.current_runs: set[str] = set()
        self.payloads: dict[str, Any] = {}
        self.failures: dict[str, ForecastDataError] = {}
        self.prepared_assets: dict[str, str] = {}

    def clear(self) -> None:
        self.catalog = None
        self.catalogs.clear()
        self.current_catalog = None
        self.current_runs.clear()
        self.payloads.clear()
        self.failures.clear()
        self.prepared_assets.clear()

    def discover_runs(self, requirements: Any, **kwargs: Any) -> Any:
        if self.catalog is None:
            raise LocalWeatherRequest(self.model)
        runs: dict[Any, Any] = {}
        failure: Exception | None = None
        for catalog in self.catalogs:
            try:
                for run in self._discover_catalog(requirements, catalog, **kwargs):
                    runs.setdefault(run.run_utc, run)
            except LocalWeatherError as error:
                failure = error
        if not runs:
            raise failure or LocalWeatherError(
                "WEATHER_RUN_UNAVAILABLE", "予報配信情報を読み取れません。",
            )
        return tuple(runs[key] for key in sorted(runs, reverse=True))

    def _discover_catalog(self, requirements: Any, catalog: WeatherCatalog, **kwargs: Any) -> Any:
        urls = super().listing_urls(requirements)  # type: ignore[misc]
        if any(url not in catalog.listings for url in urls):
            raise LocalWeatherError("WEATHER_DISCOVERY_FAILED", "予報配信情報を読み取れません。")
        try:
            return super().discover_runs(  # type: ignore[misc]
                requirements, listings=catalog.listings, **kwargs,
            )
        except (NoCompatibleRunError, GsmRunUnavailableError) as error:
            raise LocalWeatherError("WEATHER_RUN_UNAVAILABLE", str(error)) from error

    def prepare_run(self, run: Any, requirements: Any, **kwargs: Any) -> Any:
        if self.catalog is None:
            raise LocalWeatherRequest(self.model)
        self.prepared_assets.pop(str(run), None)
        failure: ForecastDataError = LocalWeatherError(
            "WEATHER_PREPARED_UNAVAILABLE",
            f"選択した{self.model} Runの配信データがありません。",
        )
        for catalog in self.catalogs:
            asset = next((item for item in catalog.assets if item.run == str(run)), None)
            if asset is None:
                continue
            if asset.sha256 in self.failures:
                failure = self.failures[asset.sha256]
                continue
            if asset.sha256 not in self.payloads:
                raise LocalWeatherRequest(self.model, asset)
            try:
                # Validate identity against the listing that described this payload,
                # never against a newer catalog's potentially different source files.
                options = dict(kwargs)
                options["available_runs"] = self._discover_catalog(requirements, catalog)
                prepared = super().prepare_run(  # type: ignore[misc]
                    run, requirements, prepared_data=self.payloads[asset.sha256], **options,
                )
                self.prepared_assets[str(run)] = asset.sha256
                if catalog is self.current_catalog:
                    self.current_runs.add(str(run))
                return prepared
            except (CacheIntegrityError, GsmCacheIntegrityError) as error:
                failure = LocalWeatherError("WEATHER_PAYLOAD_INTEGRITY_FAILED", str(error))
            except (
                MissingVariableError, SelectedRunCoverageError, GsmRunUnavailableError,
            ) as error:
                failure = LocalWeatherError("WEATHER_PREPARED_UNAVAILABLE", str(error))
            except LocalWeatherError as error:
                failure = error
        raise failure


class _MsmClient(_PortableClient, MsmClient):  # type: ignore[misc]
    model: ForecastModel = "MSM"


class _GsmClient(_PortableClient, GsmClient):  # type: ignore[misc]
    model: ForecastModel = "GSM"


class _MsmProvider(MsmWeatherProvider):
    def check_run(self, run: str, requirement: ForecastRequirement) -> None:
        # Preparation alone does not validate requested forecast values. Keep the
        # other catalog snapshots eligible until the complete check succeeds.
        while True:
            try:
                super().check_run(run, requirement)
                return
            except ForecastDataError as error:
                sha256 = self.client.prepared_assets.pop(run, None)
                if sha256 is None or sha256 in self.client.failures:
                    raise
                self.client.failures[sha256] = error
                self.client.current_runs.discard(run)


class LocalForecastWeather:
    def __init__(self) -> None:
        self.clients: dict[ForecastModel, _PortableClient] = {
            "MSM": _MsmClient(), "GSM": _GsmClient(),
        }
        self.provider = ForecastWeatherProvider({
            "MSM": _MsmProvider("unused-browser-cache", client=self.clients["MSM"]),
            "GSM": GsmWeatherProvider("unused-browser-cache", client=self.clients["GSM"]),
        })

    def begin(self) -> None:
        # Once per user action, not per synchronous replay. Browser Cache API
        # remains the only warm-acquisition path; previous arrays cannot hide IO errors.
        for client in self.clients.values():
            client.clear()
        self.provider.begin_calculation()

    def catalog(self, model: ForecastModel, text: str, *, current: bool = True) -> None:
        client = self.clients[model]
        try:
            catalog = WeatherCatalog.model_validate_json(text)
        except ValueError as error:
            raise LocalWeatherError(
                "WEATHER_CATALOG_INVALID", f"{model}配信情報が破損しています。",
            ) from error
        now = datetime.now(UTC)
        if (catalog.generated_at > now + CATALOG_CLOCK_SKEW
                or (model == "GSM" and catalog.expires_at <= now)):
            raise LocalWeatherError(
                "WEATHER_CATALOG_EXPIRED", f"{model}配信情報の有効期限を確認してください。",
            )
        if catalog not in client.catalogs:
            client.catalogs.append(catalog)
            client.catalogs.sort(key=lambda item: item.generated_at, reverse=True)
        client.catalog = client.catalogs[0]
        if current and catalog.expires_at > now:
            client.current_catalog = next(item for item in client.catalogs if item == catalog)

    def accept(self, model: ForecastModel, payload: bytes, sha256: str) -> None:
        # Imported at the boundary so the pinned wheel is the sole codec source.
        from jma_gpv_weather import MsmPreparedData

        client = self.clients[model]
        client.payloads.pop(sha256, None)
        asset = next((item for catalog in client.catalogs for item in catalog.assets
                      if item.sha256 == sha256), None)
        if asset is None:
            raise LocalWeatherError("WEATHER_CATALOG_INVALID", "予報取得計画がありません。")
        try:
            if len(payload) != asset.bytes:
                raise ValueError("prepared payload length differs from catalog")
            codec: Any = MsmPreparedData
            if model == "GSM":
                from jma_gpv_weather import GsmPreparedData

                codec = GsmPreparedData
            data = codec.from_bytes(payload, expected_sha256=sha256)
            if data.selection.run_utc.strftime("%Y%m%d%H%M%S") != asset.run:
                raise ValueError("prepared payload Run differs from catalog")
        except Exception as error:
            raise LocalWeatherError("WEATHER_PAYLOAD_INTEGRITY_FAILED", str(error)) from error
        client.payloads[sha256] = data
