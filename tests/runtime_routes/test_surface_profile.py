from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from apps.api.surface_profile import SurfaceProfile


def points():
    return [
        {"chainage_m": 0.0, "point": {"latitude": 60.05, "longitude": 10.01}},
        {"chainage_m": 100.0, "point": {"latitude": 60.05, "longitude": 10.11}},
        {"chainage_m": 200.0, "point": {"latitude": 60.05, "longitude": 10.19}},
    ]


def test_profile_reads_one_scene_at_existing_points_and_preserves_partial_classes(tmp_path: Path):
    raster = tmp_path / "scl.tif"
    with rasterio.open(raster, "w", driver="GTiff", height=1, width=4, count=1, dtype="uint8", crs="EPSG:3857", transform=from_origin(1_110_000, 8_420_000, 10_000, 10_000), nodata=0) as dataset:
        dataset.write(np.array([[6, 9, 9, 9]], dtype="uint8"), 1)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        item = {"id": "scene-1", "collection": "sentinel-2-l2a", "properties": {"datetime": "2026-10-25T10:00:00Z"}, "assets": {"scl": {"href": str(raster), "raster:bands": [{"scale": 1, "offset": 0, "nodata": 0}]}}}
        return httpx.Response(200, json={"features": [item]})

    profile = SurfaceProfile(tmp_path / "cache", transport=httpx.MockTransport(handler), clock=lambda: datetime(2026, 10, 26, 12, tzinfo=UTC))
    profile._public_asset = lambda href: True

    summary, source = profile.read_points(points(), "2026-10-26")

    assert len(requests) == 1
    assert json.loads(requests[0].content)["intersects"]["type"] == "LineString"
    assert summary["status"] == "partial"
    assert [row["scl_class"] for row in summary["samples"]] == [6, 9, 9]
    assert [row["condition"] for row in summary["samples"]] == ["water", "cloud", "cloud"]
    assert source["id"] == "sentinel-2-l2a"
    assert source["data"]["extraction_scope"] == "spaced_scene_classification_points"
    assert source["content_sha256"].startswith("sha256:")
    assert summary["source_content_sha256"] == source["content_sha256"]
    assert source["extraction_scope"] == "spaced_scene_classification_points"
    assert source["data"]["samples"] == summary["samples"]
    assert source["data"]["assessment_date"] == summary["assessment_date"]
    assert source["data"]["scene_id"] == summary["scene_id"]


def test_profile_rejects_invalid_points_before_any_io(tmp_path: Path):
    profile = SurfaceProfile(tmp_path, transport=httpx.MockTransport(lambda request: pytest.fail("network must not run")))

    with pytest.raises(ValueError):
        profile.read_points([{ "chainage_m": 1, "point": {"latitude": 0, "longitude": 0}}, {"chainage_m": 2, "point": {"latitude": 0, "longitude": 1}}], "2026-10-26")
    with pytest.raises(ValueError):
        profile.read_points(points(), "20261026")


def test_missing_scene_keeps_unknown_samples_without_manufactured_observation(tmp_path: Path):
    profile = SurfaceProfile(tmp_path, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"features": []})), clock=lambda: datetime(2026, 10, 26, tzinfo=UTC))

    summary, source = profile.read_points(points(), "2026-10-26")

    assert summary["status"] == "partial"
    assert summary["scene_id"] is None and summary["observed_at"] is None and summary["resolution_m"] is None
    assert all(row["scl_class"] is None and row["condition"] == "unknown" for row in summary["samples"])
    assert source["observed_at"] is None
    assert summary["source_content_sha256"] == source["content_sha256"]
    assert source["data"]["samples"] == summary["samples"]
