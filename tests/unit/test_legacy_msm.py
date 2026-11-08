from datetime import UTC, datetime
from types import SimpleNamespace

from autonavlog.domain.weather import ForecastRequirement
from autonavlog.weather.legacy_msm import LegacyMsmWeatherProvider


def test_legacy_metadata_and_action_reset(tmp_path):
    class Client:
        acquisition_metadata = {"acquisition": "cached", "reason": "LISTING_REFRESH_FAILED"}
        resets = 0
        def prepare_run(self, *args, **kwargs):
            return SimpleNamespace()
        def begin_calculation(self):
            self.resets += 1
            self.acquisition_metadata = {}
    client = Client()
    provider = LegacyMsmWeatherProvider(tmp_path, client)
    req = ForecastRequirement(valid_times_utc=(datetime(2026, 11, 8, tzinfo=UTC),))
    prepared = provider.prepare_run("20261107000000", req)
    assert prepared.metadata["acquisition"] == "cached"
    assert prepared.metadata["reason"] == "LISTING_REFRESH_FAILED"
    assert provider._prepared
    provider.begin_calculation()
    assert client.resets == 1
    assert not provider._prepared
    assert "acquisition" not in provider.prepare_run("20261107000000", req).metadata
