from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from apps.api.remote_sources import RemoteSources


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.copy_with(query=None) == httpx.URL(RemoteSources.ERA5_LAND_URL):
        assert dict(request.url.params)["hourly"] == ",".join(RemoteSources.ERA5_VARIABLES)
        return httpx.Response(200, json={
            "latitude": 59.9, "longitude": 10.8, "hourly_units": {
                "time": "iso8601", "temperature_2m": "°C", "precipitation": "mm",
                "soil_temperature_0_to_7cm": "°C", "soil_moisture_0_to_7cm": "m³/m³",
                "soil_temperature_7_to_28cm": "°C", "soil_moisture_7_to_28cm": "m³/m³",
            },
            "hourly": {"time": ["2024-01-15T00:00"], "temperature_2m": [-8.4], "precipitation": [0.1],
                       "soil_temperature_0_to_7cm": [-2.1], "soil_moisture_0_to_7cm": [0.31],
                       "soil_temperature_7_to_28cm": [0.3], "soil_moisture_7_to_28cm": [0.29]},
        })
    if request.url == httpx.URL(RemoteSources.STAC_URL) and request.method == "POST":
        collection = json.loads(request.content)["collections"][0]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [{
            "id": f"{collection}-actual-item", "collection": collection,
            "properties": {"datetime": "2024-01-14T10:12:00Z", "eo:cloud_cover": 3.0,
                           "sar:instrument_mode": "IW", "sar:polarizations": ["VV", "VH"]},
            "assets": {"visual": {"href": "https://signed.example/private?token=secret", "type": "image/tiff; application=geotiff"}},
        }]})
    if request.url.copy_with(query=None) == httpx.URL(RemoteSources.FORECAST_URL):
        model = dict(request.url.params)["models"]
        return httpx.Response(200, json={
            "latitude": 59.9, "longitude": 10.8, "utc_offset_seconds": 0,
            "hourly_units": {"time": "iso8601", "temperature_2m": "°C", "precipitation": "mm", "soil_moisture_0_to_1cm": "m³/m³"},
            "hourly": {"time": ["2026-10-25T00:00"], "temperature_2m": [3.5], "precipitation": [0.2], "soil_moisture_0_to_1cm": [0.3]},
            "model": model,
        })
    raise AssertionError(f"unexpected request {request.method} {request.url}")


def test_read_returns_actual_era5_values_and_honest_satellite_discovery(tmp_path: Path) -> None:
    sources = RemoteSources(tmp_path, transport=httpx.MockTransport(handler))

    result = sources.read(59.91, 10.75, "2024-01-15")

    assert set(result) == {"satellites", "history", "sources"}
    assert result["history"]["series"][0]["soil_moisture_0_to_7cm"] == 0.31
    assert result["history"]["source_id"] == "era5-land"
    assert result["satellites"]["sentinel_1"]["status"] == "partial"
    assert result["satellites"]["sentinel_2"]["status"] == "partial"
    records = {item["id"]: item for item in result["sources"]}
    assert records["era5-land"]["status"] == "available"
    assert records["sentinel-1-grd"]["status"] == "partial"
    assert "secret" not in json.dumps(result)
    assert all(set(item) == {"id", "name", "product", "version", "status", "qc", "note", "retrieved_at", "observed_at", "content_sha256", "data"} for item in result["sources"])


def test_sentinel2_uses_nearest_earlier_scene_in_ten_day_past_window_and_decodes_pixel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def stac(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(RemoteSources.STAC_URL):
            body = json.loads(request.content)
            assert body["datetime"] == "2024-01-05T00:00:00Z/2024-01-15T23:59:59Z"
            return httpx.Response(200, json={"features": [
                {"id": "future", "collection": "sentinel-2-l2a", "properties": {"datetime": "2024-01-16T10:00:00Z"}},
                {"id": "earlier", "collection": "sentinel-2-l2a", "properties": {"datetime": "2024-01-13T10:00:00Z", "eo:cloud_cover": 4.0}, "assets": {}},
            ]})
        return httpx.Response(503)

    def decoded(self: RemoteSources, item: dict[str, object], latitude: float, longitude: float) -> tuple[dict[str, object], bytes]:
        assert item["id"] == "earlier"
        return ({"bands": {"blue": {"value": 0.123, "unit": "reflectance", "scale": 0.0001, "nodata": 0}}, "scl": {"value": 4, "unit": "SCL_class"}, "qc": {"status": "available", "cloud_or_shadow": False}, "window": {"width": 1, "height": 1}}, b"raster-evidence")

    monkeypatch.setattr(RemoteSources, "_decode_sentinel2", decoded)
    result = RemoteSources(tmp_path, transport=httpx.MockTransport(stac))._sentinel("sentinel_2", "sentinel-2-l2a", 59.91, 10.75, __import__("datetime").date(2024, 1, 15), "2024-01-15T12:00:00Z")

    satellite, source = result
    assert satellite["status"] == "available"
    assert satellite["item"]["id"] == "earlier"
    assert satellite["scene_age_days"] == 2
    assert source["observed_at"] == "2024-01-13T10:00:00Z"
    assert source["data"]["pixel"]["bands"]["blue"]["unit"] == "reflectance"
    assert source["content_sha256"].startswith("sha256:")
    assert 'Зчитано' in source['note']


def test_forecast_mirrors_return_numerical_model_values_with_explicit_mirror_provenance(tmp_path: Path) -> None:
    result = RemoteSources(tmp_path, transport=httpx.MockTransport(handler)).read(59.91, 10.75, "2026-10-25")

    records = {item["id"]: item for item in result["sources"]}
    for source_id, model, variables in (("ecmwf-ifs", "ecmwf_ifs025", ["temperature_2m", "precipitation", "soil_moisture_0_to_1cm"]), ("ecmwf-aifs", "ecmwf_aifs025_single", ["temperature_2m", "precipitation", "soil_moisture_0_to_1cm"]), ("noaa-gfs", "gfs_seamless", ["temperature_2m", "precipitation"])):
        record = records[source_id]
        assert record["status"] == "available"
        assert record["data"]["model"] == model
        assert record["data"]["variables"] == variables
        assert record["data"]["provenance"] == "Open-Meteo model mirror; free non-commercial prototype, not a direct provider read"
        assert record["data"]["series"][0]["temperature_2m"] == 3.5


def test_context_source_ids_replace_existing_bootstrap_rows(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from apps.api.main import create_app

    monkeypatch.setenv("GROUNDSENSE_DATABASE_URL", "sqlite:///" + str(tmp_path / "app.db"))
    monkeypatch.setenv("GROUNDSENSE_DATA_DIR", str(tmp_path / "data"))
    with TestClient(create_app(), base_url="https://testserver") as client:
        bootstrap = client.get("/api/v1/bootstrap").json()
    result = RemoteSources(tmp_path / "adapter", transport=httpx.MockTransport(handler)).read(59.91, 10.75, "2026-10-25")
    declared_ids = {row["id"] for row in bootstrap["sources"]}
    returned_ids = [row["id"] for row in result["sources"]]
    assert len(returned_ids) == len(set(returned_ids))
    assert set(returned_ids) <= declared_ids


def test_canopy_catalogues_match_the_actual_native_tcd_reference_year(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    from apps.api.tree_cover_density import TreeCoverDensity

    monkeypatch.setenv("GROUNDSENSE_DATABASE_URL", "sqlite:///" + str(tmp_path / "app.db"))
    monkeypatch.setenv("GROUNDSENSE_DATA_DIR", str(tmp_path / "data"))
    with TestClient(create_app(), base_url="https://testserver") as client:
        bootstrap = client.get("/api/v1/bootstrap").json()
    canopy, native = TreeCoverDensity(tmp_path / "canopy", transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"value": "73"}))).read_point(59.985, 10.733)
    catalogue = next(source for source in bootstrap["sources"] if source["id"] == native["id"])
    legacy = next(source for source in RemoteSources(tmp_path / "remote")._catalogue_sources("2026-10-26T00:00:00Z") if source["id"] == native["id"])
    assert catalogue["product"] == f"Tree Cover Density {canopy['reference_year']}"
    assert legacy["version"] == native["version"] == str(canopy["reference_year"])


def test_read_marks_a_failed_provider_unavailable_without_synthetic_fallback(tmp_path: Path) -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    result = RemoteSources(tmp_path, transport=httpx.MockTransport(unavailable)).read(59.91, 10.75, "2024-01-15")

    records = {item["id"]: item for item in result["sources"]}
    assert records["era5-land"]["status"] == "unavailable"
    assert result["history"]["series"] == []
    assert all(item["status"] != "available" for item in records.values())


def test_cache_is_bounded_and_constructor_does_not_make_network_calls(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    def count(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    sources = RemoteSources(tmp_path, transport=httpx.MockTransport(count), cache_max_entries=1)
    assert calls == []
    sources.read(59.91, 10.75, "2024-01-15")
    sources.read(59.92, 10.75, "2024-01-15")
    assert len(list((tmp_path / "indexes").glob("*.json"))) <= 1


@pytest.mark.parametrize("latitude, longitude, date", [(91, 10.75, "2024-01-15"), (59.91, 10.75, "not-a-date")])
def test_read_rejects_invalid_coordinates_and_dates(tmp_path: Path, latitude: float, longitude: float, date: str) -> None:
    with pytest.raises(ValueError):
        RemoteSources(tmp_path).read(latitude, longitude, date)


def test_forecast_requests_and_returned_rows_belong_to_the_selected_day(tmp_path):
    requests = []
    def dated(request):
        if request.url.copy_with(query=None) == httpx.URL(RemoteSources.FORECAST_URL):
            params = dict(request.url.params)
            requests.append(params)
            assert params.get("start_date") == params.get("end_date") == "2024-01-15"
            payload = handler(request).json()
            payload["hourly"]["time"] = ["2024-01-15T00:00"]
            return httpx.Response(200, json=payload)
        return handler(request)
    result = RemoteSources(tmp_path, transport=httpx.MockTransport(dated)).read(59.91, 10.75, "2024-01-15")
    assert len(requests) == 3
    for source in result["sources"]:
        if source["id"] in {row[0] for row in RemoteSources.FORECAST_MODELS}:
            assert source["status"] == "available"
            assert source["data"]["series"][0]["time"].startswith("2024-01-15T")


def test_wrong_day_response_is_not_presented_as_selected_day_data(tmp_path):
    result = RemoteSources(tmp_path, transport=httpx.MockTransport(handler)).read(59.91, 10.75, "2024-01-15")
    model_ids = {row[0] for row in RemoteSources.FORECAST_MODELS}
    assert all(s["status"] == "unavailable" for s in result["sources"] if s["id"] in model_ids)


@pytest.mark.parametrize("missing,expected", [("all", "unavailable"), ("precipitation", "partial")])
def test_null_model_values_do_not_pass_numeric_quality_control(tmp_path, missing, expected):
    def incomplete(request):
        response = handler(request)
        if request.url.copy_with(query=None) in {httpx.URL(RemoteSources.FORECAST_URL), httpx.URL(RemoteSources.ERA5_LAND_URL)}:
            payload = response.json()
            payload["hourly"]["time"] = ["2024-01-15T00:00"]
            for key in payload["hourly"]:
                if key != "time" and (missing == "all" or key == missing):
                    payload["hourly"][key] = [None]
            return httpx.Response(200, json=payload)
        return response
    result = RemoteSources(tmp_path, transport=httpx.MockTransport(incomplete)).read(59.91, 10.75, "2024-01-15")
    numeric_ids = {"era5-land", *(row[0] for row in RemoteSources.FORECAST_MODELS)}
    for source in result["sources"]:
        if source["id"] in numeric_ids:
            assert source["status"] == source["qc"] == expected
            if missing == "all":
                assert source["observed_at"] is None


def test_same_context_reuses_fresh_reads_without_mutating_cached_provenance(tmp_path):
    calls = []
    def counted(request):
        calls.append(request)
        return handler(request)
    adapter = RemoteSources(tmp_path, transport=httpx.MockTransport(counted))
    first = adapter.read(59.91, 10.75, "2024-01-15")
    count = len(calls)
    first["history"]["series"][0]["soil_moisture_0_to_7cm"] = 999
    second = adapter.read(59.91, 10.75, "2024-01-15")
    assert len(calls) == count
    assert second["history"]["series"][0]["soil_moisture_0_to_7cm"] == .31
    assert second["sources"][0]["retrieved_at"] == first["sources"][0]["retrieved_at"]
