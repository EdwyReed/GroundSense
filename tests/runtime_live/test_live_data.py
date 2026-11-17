from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest

from apps.api.live_data import LiveDataError, LiveWeatherClient


NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
HOURS = ["2026-10-25T00:00", "2026-10-25T01:00", "2026-10-26T00:00"]
RESEARCH_VARIABLES = (
    "et0_fao_evapotranspiration",
    "soil_moisture_3_to_9cm",
    "snow_depth",
    "snowfall",
)


def provider_payload(**changes):
    payload = {
        "latitude": 59.91,
        "longitude": 10.75,
        "elevation": 23.0,
        "hourly_units": {
            "time": "iso8601",
            "temperature_2m": "°C",
            "precipitation": "mm",
            "soil_moisture_0_to_1cm": "m³/m³",
            "soil_moisture_1_to_3cm": "m³/m³",
            "soil_temperature_0cm": "°C",
        },
        "hourly": {
            "time": HOURS,
            "temperature_2m": [3.5, 3.0, 2.5],
            "precipitation": [0.1, 0.0, 0.0],
            "soil_moisture_0_to_1cm": [0.2, None, 0.22],
            "soil_moisture_1_to_3cm": [0.25, 0.26, 0.27],
            "soil_temperature_0cm": [4.0, 4.1, 4.2],
        },
    }
    payload.update(changes)
    return payload


def research_payload(hours=None):
    hours = hours or [
        "2026-10-25T00:00", "2026-10-25T01:00", "2026-10-26T00:00",
        "2026-10-28T00:00", "2026-10-28T01:00",
    ]
    count = len(hours)
    payload = provider_payload()
    payload["hourly_units"].update({
        "et0_fao_evapotranspiration": "mm",
        "soil_moisture_3_to_9cm": "m³/m³",
        "snow_depth": "m",
        "snowfall": "cm",
    })
    payload["hourly"] = {
        "time": hours,
        "temperature_2m": [3.5] * count,
        "precipitation": [0.1] * count,
        "soil_moisture_0_to_1cm": [0.2] * count,
        "soil_moisture_1_to_3cm": [0.25] * count,
        "soil_temperature_0cm": [4.0] * count,
        "et0_fao_evapotranspiration": [0.01] * count,
        "soil_moisture_3_to_9cm": [0.3] * count,
        "snow_depth": [0.0] * count,
        "snowfall": [0.0] * count,
    }
    return payload


def transport(payload, status_code=200, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(status_code, json=payload, request=request)
    return httpx.MockTransport(handler)


def client(tmp_path, payload=None, **kwargs):
    return LiveWeatherClient(
        tmp_path / "cache", transport=transport(payload or provider_payload()),
        clock=lambda: NOW, **kwargs,
    )


def test_forecast_maps_selected_utc_day_and_retains_raw_snapshot(tmp_path):
    payload = provider_payload()
    api = client(tmp_path, payload)

    result = api.forecast(59.91, 10.75, "2026-10-25")

    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    assert result["mode"] == "live"
    assert result["synthetic"] is False
    assert result["assessment_date"] == "2026-10-25"
    assert result["requested_point"] == {"latitude": 59.91, "longitude": 10.75}
    assert result["grid_point"] == {"latitude": 59.91, "longitude": 10.75, "elevation_m": 23.0}
    assert result["source"]["model"] == "icon_global"
    assert result["source"]["issue_time"] is None
    assert result["source"]["service_usage"] == "non_commercial_prototype"
    assert result["source"]["cached"] is False
    assert result["source"]["content_sha256"] == f"sha256:{digest}"
    assert result["series"] == [{
        "time": "2026-10-25T00:00:00Z", "temperature_2m": 3.5,
        "precipitation": 0.1, "soil_moisture_0_to_1cm": 0.2,
        "soil_moisture_1_to_3cm": 0.25, "soil_temperature_0cm": 4.0,
        "precipitation_interval_start": "2026-10-24T23:00:00Z",
        "precipitation_interval_end": "2026-10-25T00:00:00Z",
    }, {
        "time": "2026-10-25T01:00:00Z", "temperature_2m": 3.0,
        "precipitation": 0.0, "soil_moisture_0_to_1cm": None,
        "soil_moisture_1_to_3cm": 0.26, "soil_temperature_0cm": 4.1,
        "precipitation_interval_start": "2026-10-25T00:00:00Z",
        "precipitation_interval_end": "2026-10-25T01:00:00Z",
    }]
    assert result["qc"] == {"status": "partial", "missing_variables": ["soil_moisture_0_to_1cm"], "is_observation": False, "spatial_support": "model_grid_not_road"}
    assert api.snapshot_path(digest).read_bytes() == raw


def test_forecast_uses_fixed_icon_global_https_request(tmp_path):
    calls = []
    api = LiveWeatherClient(tmp_path / "cache", transport=transport(provider_payload(), calls=calls), clock=lambda: NOW)

    api.forecast(59.91, 10.75, "2026-10-25")

    request = calls[0]
    assert str(request.url).startswith("https://api.open-meteo.com/v1/forecast?")
    assert request.url.params["models"] == "icon_global"
    assert request.url.params["forecast_days"] == "7"
    assert request.url.params["timezone"] == "UTC"
    assert request.url.params["hourly"] == "temperature_2m,precipitation,soil_moisture_0_to_1cm,soil_moisture_1_to_3cm,soil_temperature_0cm,et0_fao_evapotranspiration,soil_moisture_3_to_9cm,snow_depth,snowfall"


def test_forecast_exposes_research_window_through_72_hour_boundary(tmp_path):
    result = client(tmp_path, research_payload()).forecast(59.91, 10.75, "2026-10-25")

    assert [row["time"] for row in result["series"]] == [
        "2026-10-25T00:00:00Z", "2026-10-25T01:00:00Z",
    ]
    assert [row["time"] for row in result["research_series"]] == [
        "2026-10-25T00:00:00Z", "2026-10-25T01:00:00Z",
        "2026-10-26T00:00:00Z", "2026-10-28T00:00:00Z",
    ]
    boundary = result["research_series"][-1]
    assert boundary["et0_fao_evapotranspiration"] == 0.01
    assert boundary["precipitation_interval_start"] == "2026-10-27T23:00:00Z"
    assert boundary["precipitation_interval_end"] == "2026-10-28T00:00:00Z"
    assert boundary["et0_fao_evapotranspiration_interval_start"] == "2026-10-27T23:00:00Z"
    assert boundary["et0_fao_evapotranspiration_interval_end"] == "2026-10-28T00:00:00Z"
    assert result["research_qc"] == {"status": "available", "missing_variables": []}


def test_forecast_keeps_optional_research_fields_null_when_provider_omits_them(tmp_path):
    payload = research_payload()
    for name in RESEARCH_VARIABLES:
        payload["hourly_units"].pop(name)
        payload["hourly"].pop(name)

    result = client(tmp_path, payload).forecast(59.91, 10.75, "2026-10-25")

    assert all(row[name] is None for row in result["research_series"] for name in RESEARCH_VARIABLES)
    assert result["research_qc"] == {"status": "partial", "missing_variables": sorted(RESEARCH_VARIABLES)}


def test_forecast_marks_all_null_optional_research_column_partial(tmp_path):
    payload = research_payload()
    payload["hourly"]["snow_depth"] = [None] * len(payload["hourly"]["time"])

    result = client(tmp_path, payload).forecast(59.91, 10.75, "2026-10-25")

    assert all(row["snow_depth"] is None for row in result["research_series"])
    assert result["research_qc"] == {"status": "partial", "missing_variables": ["snow_depth"]}


def test_forecast_rejects_optional_research_column_with_wrong_unit_without_breaking_weather_read(tmp_path):
    payload = research_payload()
    payload["hourly_units"]["snowfall"] = "mm"

    result = client(tmp_path, payload).forecast(59.91, 10.75, "2026-10-25")

    assert result["series"][0]["precipitation"] == 0.1
    assert all(row["snowfall"] is None for row in result["research_series"])
    assert result["research_qc"] == {"status": "partial", "missing_variables": ["snowfall"]}


def test_forecast_preserves_provider_time_gaps_in_research_series(tmp_path):
    payload = research_payload([
        "2026-10-25T00:00", "2026-10-25T02:00", "2026-10-28T00:00",
    ])

    result = client(tmp_path, payload).forecast(59.91, 10.75, "2026-10-25")

    assert [row["time"] for row in result["research_series"]] == [
        "2026-10-25T00:00:00Z", "2026-10-25T02:00:00Z", "2026-10-28T00:00:00Z",
    ]


def test_forecast_stops_research_window_at_provider_horizon(tmp_path):
    payload = research_payload(["2026-10-25T00:00", "2026-10-27T00:00"])

    result = client(tmp_path, payload).forecast(59.91, 10.75, "2026-10-25")

    assert [row["time"] for row in result["research_series"]] == [
        "2026-10-25T00:00:00Z", "2026-10-27T00:00:00Z",
    ]


def test_forecast_ignores_extra_provider_native_variable(tmp_path):
    payload = research_payload()
    payload["hourly_units"]["cloud_cover"] = "%"
    payload["hourly"]["cloud_cover"] = [0] * len(payload["hourly"]["time"])

    result = client(tmp_path, payload).forecast(59.91, 10.75, "2026-10-25")

    assert "cloud_cover" not in result["research_series"][0]
    assert result["research_qc"]["status"] == "available"


def test_forecast_does_not_use_legacy_five_variable_cache_entry(tmp_path):
    cache = tmp_path / "cache"
    calls = []
    api = LiveWeatherClient(cache, transport=transport(research_payload(), calls=calls), clock=lambda: NOW)
    raw = json.dumps(provider_payload(), ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    legacy_key = hashlib.sha256(b"59.91000000|10.75000000|2026-10-25").hexdigest()
    api._store(legacy_key, raw, digest, "https://legacy.invalid/", NOW)

    result = api.forecast(59.91, 10.75, "2026-10-25")

    assert len(calls) == 1
    assert result["source"]["cached"] is False
    assert result["research_series"][0]["snowfall"] == 0.0


def test_fresh_cache_avoids_second_upstream_request(tmp_path):
    calls = []
    api = LiveWeatherClient(tmp_path / "cache", transport=transport(provider_payload(), calls=calls), clock=lambda: NOW)

    first = api.forecast(59.91, 10.75, "2026-10-25")
    second = api.forecast(59.91, 10.75, "2026-10-25")

    assert len(calls) == 1
    assert first["source"]["cached"] is False
    assert second["source"]["cached"] is True


@pytest.mark.parametrize("bad_value", [True, float("nan"), float("inf")])
def test_forecast_rejects_boolean_and_nonfinite_numeric_values(tmp_path, bad_value):
    payload = provider_payload()
    payload["hourly"]["temperature_2m"][0] = bad_value

    if isinstance(bad_value, float):
        raw = json.dumps(payload, allow_nan=True).encode()
        api = LiveWeatherClient(
            tmp_path / "cache",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw, request=request)),
            clock=lambda: NOW,
        )
    else:
        api = client(tmp_path, payload)
    with pytest.raises(LiveDataError) as error:
        api.forecast(59.91, 10.75, "2026-10-25")

    assert error.value.status_code == 502


def test_forecast_rejects_wrong_provider_units(tmp_path):
    payload = provider_payload()
    payload["hourly_units"]["precipitation"] = "cm"

    with pytest.raises(LiveDataError) as error:
        client(tmp_path, payload).forecast(59.91, 10.75, "2026-10-25")

    assert error.value.status_code == 502


def test_forecast_does_not_use_stale_cache_after_upstream_failure(tmp_path):
    good = client(tmp_path, provider_payload(), cache_ttl_seconds=1)
    good.forecast(59.91, 10.75, "2026-10-25")

    def failing(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")
    stale = LiveWeatherClient(tmp_path / "cache", transport=httpx.MockTransport(failing), clock=lambda: NOW.replace(second=2), cache_ttl_seconds=1)

    with pytest.raises(LiveDataError) as error:
        stale.forecast(59.91, 10.75, "2026-10-25")

    assert error.value.status_code == 503


def test_forecast_rejects_date_outside_provider_horizon(tmp_path):
    with pytest.raises(LiveDataError) as error:
        client(tmp_path).forecast(59.91, 10.75, "2026-11-01")

    assert error.value.status_code == 422


def test_cached_result_preserves_original_retrieval_time(tmp_path):
    api = client(tmp_path)
    first = api.forecast(59.91, 10.75)
    later = LiveWeatherClient(tmp_path/'cache', clock=lambda: NOW.replace(second=30))
    assert later.forecast(59.91, 10.75)['source']['retrieved_at'] == first['source']['retrieved_at']


def test_cache_eviction_preserves_content_addressed_evidence(tmp_path):
    api = client(tmp_path, cache_max_entries=1)
    first = api.forecast(59.91, 10.75)
    digest = first['source']['content_sha256'].removeprefix('sha256:')
    # Different bytes guarantee a second content address; the old raw evidence must survive.
    api._transport = transport(provider_payload(elevation=24))
    api.forecast(59.92, 10.75)
    assert api.snapshot_path(digest).is_file()


def test_provider_non_utc_timebase_is_rejected(tmp_path):
    with pytest.raises(LiveDataError):
        client(tmp_path, provider_payload(utc_offset_seconds=3600)).forecast(59.91, 10.75)


def test_duplicate_provider_hours_are_rejected(tmp_path):
    payload = provider_payload()
    payload['hourly']['time'] = [HOURS[0], HOURS[0], HOURS[2]]
    with pytest.raises(LiveDataError):
        client(tmp_path, payload).forecast(59.91, 10.75)
