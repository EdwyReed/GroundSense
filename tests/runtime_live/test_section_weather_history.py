from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from apps.api.live_data import LiveDataError, LiveWeatherClient

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


def _payload(hours: int = 336) -> dict:
    start = datetime(2026, 10, 19, tzinfo=UTC)
    times = [(start + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M") for index in range(hours)]
    return {
        "latitude": 60.0, "longitude": 10.75, "elevation": 272.0, "utc_offset_seconds": 0,
        "hourly_units": {"time": "iso8601", "temperature_2m": "°C", "precipitation": "mm", "soil_moisture_0_to_1cm": "m³/m³", "soil_moisture_1_to_3cm": "m³/m³", "soil_temperature_0cm": "°C", "et0_fao_evapotranspiration": "mm", "soil_moisture_3_to_9cm": "m³/m³", "snow_depth": "m", "snowfall": "cm"},
        "hourly": {name: values for name, values in {
            "time": times, "temperature_2m": [2.0] * hours, "precipitation": [0.5] * hours,
            "soil_moisture_0_to_1cm": [0.2] * hours, "soil_moisture_1_to_3cm": [0.3] * hours,
            "soil_temperature_0cm": [1.0] * hours, "et0_fao_evapotranspiration": [0.1] * hours,
            "soil_moisture_3_to_9cm": [0.25] * hours, "snow_depth": [0.0] * hours, "snowfall": [0.0] * hours,
        }.items()},
    }


def test_section_request_adds_past_days_returns_bounded_history_and_uses_isolated_cache(tmp_path):
    calls: list[httpx.Request] = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_payload(), request=request)
    api = LiveWeatherClient(tmp_path / "cache", transport=httpx.MockTransport(handler), clock=lambda: NOW)
    assert calls == []  # Constructor remains network-free.

    section = api.forecast_for_section(60.0, 10.75, "2026-10-26")
    cached = api.forecast_for_section(60.0, 10.75, "2026-10-26")
    legacy = api.forecast(60.0, 10.75, "2026-10-26")

    assert len(calls) == 2
    assert calls[0].url.params["past_days"] == "7"
    assert calls[0].url.params["forecast_days"] == "7"
    assert section["source"]["cached"] is False
    assert cached["source"]["cached"] is True
    assert legacy["source"]["cached"] is False
    assert len(section["antecedent_series"]) == 169
    assert section["antecedent_series"][0]["time"] == "2026-10-19T00:00:00Z"
    assert section["antecedent_series"][-1]["time"] == "2026-10-26T00:00:00Z"
    assert section["research_series"] == legacy["research_series"]


def test_section_rejects_over_400_rows(tmp_path):
    api = LiveWeatherClient(tmp_path / "cache", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_payload(401), request=request)), clock=lambda: NOW)
    with pytest.raises(LiveDataError) as error:
        api.forecast_for_section(60.0, 10.75, "2026-10-25")
    assert error.value.status_code == 502


def test_section_rejects_over_one_mebibyte_wire_body(tmp_path):
    content = b"x" * (1024 * 1024 + 1)
    api = LiveWeatherClient(tmp_path / "cache", transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content, request=request)), clock=lambda: NOW)
    with pytest.raises(LiveDataError) as error:
        api.forecast_for_section(60.0, 10.75, "2026-10-25")
    assert error.value.status_code == 502


def test_section_rejects_nonhourly_rows_instead_of_exceeding_169_history_timestamps(tmp_path):
    payload = _payload(400)
    start = datetime(2026, 10, 19, tzinfo=UTC)
    payload['hourly']['time'] = [(start + timedelta(minutes=30 * index)).strftime('%Y-%m-%dT%H:%M') for index in range(400)]
    api = LiveWeatherClient(tmp_path / 'cache', transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload, request=request)), clock=lambda: NOW)
    with pytest.raises(LiveDataError):
        api.forecast_for_section(60.0, 10.75, '2026-10-25')


def test_section_aborts_oversized_stream_before_consuming_tail(tmp_path):
    consumed, closed = [], []

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            for index in range(32):
                consumed.append(index)
                yield b'x' * 65536

        def close(self):
            closed.append(True)

    api = LiveWeatherClient(tmp_path / 'cache', transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Chunks(), headers={'Content-Type': 'text/plain'}, request=request)), clock=lambda: NOW)
    with pytest.raises(LiveDataError) as error:
        api.forecast_for_section(60.0, 10.75, '2026-10-25')
    assert error.value.status_code == 502
    assert len(consumed) == 17 and closed == [True]
    assert not (tmp_path / 'cache' / 'snapshots').exists()
