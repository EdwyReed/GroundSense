from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from apps.api.surface_observation import SurfaceObservation


NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
ASSET = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/31/U/FS/2026/10/S2A_fixture/SCL.tif"


def item(identifier: str, observed: str, href: str = ASSET) -> dict:
    return {"id": identifier, "collection": "sentinel-2-l2a", "properties": {"datetime": observed}, "assets": {"scl": {"href": href, "raster:bands": [{"scale": 1, "offset": 0}]}}}


def raster(path: Path, values, *, crs="EPSG:4326", transform_value=None, nodata=0, scale=1, offset=0) -> None:
    values = np.asarray(values)
    transform_value = transform_value or from_origin(10, 60.2, 0.1, 0.1)
    with rasterio.open(path, "w", driver="GTiff", height=values.shape[0], width=values.shape[1], count=1, dtype=str(values.dtype), crs=crs, transform=transform_value, nodata=nodata) as dataset:
        dataset.write(values, 1)
        dataset.scales = [scale]
        dataset.offsets = [offset]


def adapter(tmp_path: Path, features: list[dict], *, now=NOW) -> SurfaceObservation:
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        assert request.method == "POST" and request.url == httpx.URL(SurfaceObservation.STAC_URL)
        assert body["collections"] == ["sentinel-2-l2a"] and body["intersects"]["type"] == "Point"
        assert body["datetime"] == "2026-10-16T00:00:00Z/2026-10-26T12:00:00Z" and body["limit"] == 12 and body["sortby"] == [{"field": "properties.datetime", "direction": "desc"}]
        return httpx.Response(200, json={"features": features})
    result = SurfaceObservation(tmp_path, transport=httpx.MockTransport(handler), clock=lambda: now)
    result.calls = calls
    return result


def local_cog(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    original = rasterio.open
    monkeypatch.setattr(rasterio, "open", lambda value, *args, **kwargs: original(path if value == ASSET else value, *args, **kwargs))


def test_constructor_is_network_free_and_water_uses_one_native_projected_cell_with_finite_evidence(tmp_path, monkeypatch):
    path = tmp_path / "water.tif"
    xs, ys = transform("EPSG:4326", "EPSG:3857", [10.05], [60.15])
    raster(path, np.array([[6, 4]], dtype=np.uint8), crs="EPSG:3857", transform_value=from_origin(xs[0] - 50, ys[0] + 50, 100, 100))
    local_cog(monkeypatch, path)
    source = adapter(tmp_path, [item("scene", "2026-10-25T10:35:00Z")])
    assert source.calls == []

    observation, evidence = source.read_point(60.15, 10.05, "2026-10-26")

    assert observation == {"status": "available", "basis": "sentinel2_l2a_scl_point", "assessment_date": "2026-10-26", "requested_point": {"latitude": 60.15, "longitude": 10.05}, "observed_at": "2026-10-25T10:35:00Z", "retrieved_at": "2026-10-26T12:00:00Z", "scene_age_days": 1, "scene_id": "scene", "scl_class": 6, "condition": "water", "resolution_m": 100.0, "selection_scope": "bounded_catalogue_result"}
    assert evidence["id"] == "sentinel-2-l2a" and evidence["data"]["extraction_scope"] == "scene_classification_point"
    assert evidence["data"]["native"]["row"] == 0 and evidence["data"]["native"]["col"] == 0
    assert evidence["data"]["native"]["raw_class"] == 6 and evidence["data"]["native"]["window"] == {"row": 0, "col": 0, "width": 1, "height": 1}
    assert "sentinel-cogs" not in json.dumps((observation, evidence))
    json.dumps(evidence, allow_nan=False)
    assert len(source.calls) == 1


@pytest.mark.parametrize(("value", "status", "condition"), [(3, "partial", "shadow"), (8, "partial", "cloud"), (11, "partial", "snow_ice"), (0, "partial", "unknown"), (5, "available", "not_vegetated")])
def test_scl_classes_are_observational_only_and_never_dry_or_frozen(tmp_path, monkeypatch, value, status, condition):
    path = tmp_path / "class.tif"; raster(path, np.array([[value]], dtype=np.uint8)); local_cog(monkeypatch, path)
    observation, _ = adapter(tmp_path, [item("scene", "2026-10-26T10:00:00Z")]).read_point(60.15, 10.05, "2026-10-26")
    assert observation["status"] == status and observation["condition"] == condition and "dry" not in json.dumps(observation) and "frozen" not in json.dumps(observation)


@pytest.mark.parametrize("value, expected", [(0.0, 0), (np.nan, None), (np.inf, None), (6.5, None)])
def test_nodata_nan_inf_fractional_and_real_zero_are_unknown_without_fabricating_a_class(tmp_path, monkeypatch, value, expected):
    path = tmp_path / "invalid.tif"; raster(path, np.array([[value]], dtype=np.float64), nodata=-9999); local_cog(monkeypatch, path)
    observation, evidence = adapter(tmp_path, [item("scene", "2026-10-26T10:00:00Z")]).read_point(60.15, 10.05, "2026-10-26")
    assert observation["status"] == "partial" and observation["scl_class"] == expected and observation["condition"] == "unknown"
    assert evidence["data"]["native"]["raw_class"] == expected
    json.dumps(evidence, allow_nan=False)


def test_exact_native_edge_and_outside_are_not_clamped(tmp_path, monkeypatch):
    path = tmp_path / "edge.tif"; raster(path, np.array([[6]], dtype=np.uint8), transform_value=from_origin(10, 60.2, 0.1, 0.1)); local_cog(monkeypatch, path)
    source = adapter(tmp_path, [item("scene", "2026-10-26T10:00:00Z")])
    inside, _ = source.read_point(60.15, 10.05, "2026-10-26")
    outside, _ = source.read_point(60.2, 10.1, "2026-10-26")
    assert inside["scl_class"] == 6
    assert outside["status"] == "partial" and outside["scl_class"] is None


def test_scene_selection_uses_retrieval_instant_and_never_searches_old_clear_scene_after_latest_cloud(tmp_path, monkeypatch):
    path = tmp_path / "cloud.tif"; raster(path, np.array([[8]], dtype=np.uint8)); local_cog(monkeypatch, path)
    observations, _ = adapter(tmp_path, [item("future", "2026-10-26T13:00:00Z"), item("cloud", "2026-10-26T11:00:00Z"), item("old-clear", "2026-10-25T10:00:00Z")]).read_point(60.15, 10.05, "2026-10-26")
    assert observations["scene_id"] == "cloud" and observations["condition"] == "cloud" and observations["status"] == "partial"


def test_no_scene_malformed_response_unsafe_url_and_provider_failure_are_safe_unknown(tmp_path):
    no_scene = adapter(tmp_path / "none", [])
    observation, evidence = no_scene.read_point(60.15, 10.05, "2026-10-26")
    assert observation["status"] == "partial" and observation["scene_id"] is None and evidence["status"] == "partial"
    unsafe = adapter(tmp_path / "unsafe", [item("scene", "2026-10-26T10:00:00Z", "https://evil.invalid/x.tif?sig=secret")])
    observation, evidence = unsafe.read_point(60.15, 10.05, "2026-10-26")
    assert observation["status"] == "partial" and "secret" not in json.dumps((observation, evidence))
    broken = SurfaceObservation(tmp_path / "broken", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"features": "bad"})), clock=lambda: NOW)
    observation, evidence = broken.read_point(60.15, 10.05, "2026-10-26")
    assert observation["status"] == "unavailable" and "ValueError" not in json.dumps((observation, evidence))


def test_five_minute_cache_deepcopies_and_bounds_entries(tmp_path, monkeypatch):
    path = tmp_path / "cache.tif"; raster(path, np.array([[6]], dtype=np.uint8)); local_cog(monkeypatch, path)
    now = [NOW]
    source = adapter(tmp_path, [item("scene", "2026-10-26T10:00:00Z")], now=now[0])
    first, _ = source.read_point(60.15, 10.05, "2026-10-26"); first["condition"] = "corrupt"
    second, _ = source.read_point(60.15, 10.05, "2026-10-26")
    assert second["condition"] == "water" and len(source.calls) == 1
    for number in range(65):
        source.read_point(60.15, 10.05 + number / 10_000, "2026-10-26")
    assert source.cache_size <= 64
