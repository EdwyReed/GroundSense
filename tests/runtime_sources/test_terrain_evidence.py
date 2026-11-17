from __future__ import annotations

import math
from pathlib import Path

import pytest

pytest.importorskip("rasterio")
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from apps.api.static_sources import StaticSources
from apps.api.terrain_evidence import TerrainEvidence


def _raster(path: Path, data, *, crs="EPSG:4326", transform_value=None, nodata=None, tags=None):
    array = np.asarray(data, dtype="float32")
    if array.ndim != 2:
        raise ValueError("test raster must be two-dimensional")
    with rasterio.open(
        path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
        count=1, dtype="float32", crs=crs,
        transform=transform_value or from_origin(10.73, 59.93, 0.02, 0.02), nodata=nodata,
    ) as dataset:
        dataset.write(array, 1)
        if tags:
            dataset.update_tags(**tags)


def test_read_exposes_bounded_local_context_from_native_rasters(tmp_path, monkeypatch):
    """The adapter reads physical DSM and WorldCover windows, not point labels."""
    x, y = transform("EPSG:4326", "EPSG:3857", [10.75], [59.91])
    dsm = tmp_path / "dsm.tif"
    cover = tmp_path / "cover.tif"
    _raster(
        dsm,
        [[80, 90, 100], [80, 90, 100], [80, 90, 100]],
        crs="EPSG:3857", transform_value=from_origin(x[0] - 45, y[0] + 45, 30, 30),
        tags={"units": "m", "vertical_datum": "EGM2008"},
    )
    _raster(cover, np.full((51, 51), 10), transform_value=from_origin(10.74745, 59.91255, 0.0001, 0.0001))
    soil = {}
    for name, value in (("sand", 426), ("silt", 337), ("clay", 79)):
        path = tmp_path / f"{name}.tif"
        _raster(path, np.full((3, 3), value), tags={"units": "g/kg", "statistic": "Q0.5"})
        soil[name] = str(path)

    static = StaticSources(tmp_path / "cache")
    monkeypatch.setattr(static, "_urls_for_point", lambda *_: {**soil, "terrain": str(dsm), "worldcover": str(cover)})
    result = TerrainEvidence(static).read(59.91, 10.75)

    assert set(result) == {"ground_composition", "local_terrain", "vegetation", "sources"}
    assert result["ground_composition"]["composition"] == {"sand": 42.6, "silt": 33.7, "clay": 7.9}
    assert result["ground_composition"]["closure"]["normalized"] is False
    terrain = result["local_terrain"]
    assert terrain["slope_degrees"] == pytest.approx(math.degrees(math.atan(10 / (30 * math.cos(math.radians(59.91))))), rel=0.05)
    assert terrain["surface_kind"] == "DSM"
    assert "not a bare-earth DTM" in terrain["note"]
    vegetation = result["vegetation"]
    assert vegetation["tree_cover_percent_of_valid"] == 100.0
    assert vegetation["valid_coverage_fraction"] == 1.0
    assert vegetation["reference_year"] == 2021
    assert "canopy density" in vegetation["note"]
    assert result["ground_composition"]["status"] == "partial"
    assert result["ground_composition"]["support_m"] == 250
    assert result["local_terrain"]["slope_deg"] == terrain["slope_degrees"]
    assert result["vegetation"]["tree_cover_percent"] == 100.0
    assert result["vegetation"]["valid_fraction"] == 1.0
    assert result["vegetation"]["footprint_m"]["width"] > 0
    assert result["vegetation"]["canopy_density_percent"] is None
    assert {source["id"] for source in result["sources"]} == {"soilgrids", "copernicus-glo-30", "esa-worldcover"}
    assert all(source["retrieved_at"] for source in result["sources"])
    assert all(source["content_sha256"].startswith("sha256:") for source in result["sources"])


def test_nodata_edges_partial_cover_and_nonclosure_stay_explicit(tmp_path, monkeypatch):
    dsm = tmp_path / "dsm-edge.tif"
    cover = tmp_path / "cover-partial.tif"
    _raster(dsm, [[1, 2], [3, 4]], nodata=-9999)
    cover_data = np.full((51, 51), 20)
    cover_data[:20, :] = -9999
    _raster(cover, cover_data, transform_value=from_origin(10.74745, 59.91255, 0.0001, 0.0001), nodata=-9999)
    soil = {}
    for name, value in (("sand", 426), ("silt", 337), ("clay", 79)):
        path = tmp_path / f"{name}.tif"
        _raster(path, np.full((3, 3), value), tags={"units": "g/kg"})
        soil[name] = str(path)
    static = StaticSources(tmp_path / "cache")
    monkeypatch.setattr(static, "_urls_for_point", lambda *_: {**soil, "terrain": str(dsm), "worldcover": str(cover)})

    result = TerrainEvidence(static).read(59.91, 10.75)

    assert result["local_terrain"]["slope_degrees"] is None
    assert "not a bare-earth DTM" in result["local_terrain"]["note"]
    assert 0 < result["vegetation"]["valid_coverage_fraction"] < 1
    assert result["vegetation"]["tree_cover_percent_of_valid"] == 0.0
    closure = result["ground_composition"]["closure"]
    assert closure["total_percent"] == pytest.approx(84.2)
    assert closure["normalized"] is False


def test_construction_is_networkless_and_transport_failure_skips_remaining_soil(tmp_path, monkeypatch):
    static = StaticSources(tmp_path / "cache")
    calls = []
    def sample(url, lat, lon):
        calls.append(url)
        return None, "raster read failed: TimeoutError: provider secret"
    monkeypatch.setattr(static, "_sample", sample)
    adapter = TerrainEvidence(static)
    assert calls == []
    monkeypatch.setattr(static, "_urls_for_point", lambda *_: {"sand": "https://approved.example/sand.tif", "terrain": None, "worldcover": None})

    result = adapter.read(59.91, 10.75)

    assert calls == ["https://approved.example/sand.tif"]
    soil_source = next(source for source in result["sources"] if source["id"] == "soilgrids")
    assert "secret" not in (soil_source["note"] or "")
    assert soil_source["status"] == "unavailable"


def test_native_windows_mask_nonfinite_pixels_and_record_actual_valid_count(tmp_path):
    dsm = tmp_path / "nan-dsm.tif"
    cover = tmp_path / "finite-cover.tif"
    _raster(dsm, [[1, 2, 3], [1, float('nan'), 3], [1, 2, 3]])
    _raster(cover, np.full((3, 3), 30))
    adapter = TerrainEvidence(StaticSources(tmp_path / "cache"))
    sample, reason = adapter._window(str(cover), 59.91, 10.75, 1)
    assert reason is None
    assert sample["evidence"]["valid_pixel_count"] == 9
    terrain, source = adapter._terrain(59.91, 10.75, str(dsm), "2026-10-26T00:00:00Z")
    assert terrain["slope_deg"] is None
    assert source["status"] == "unavailable"


def test_unknown_land_cover_codes_are_not_counted_as_known_nonforest(tmp_path):
    cover = tmp_path / "unknown-cover.tif"
    _raster(cover, np.full((3, 3), 255))
    result, source = TerrainEvidence(StaticSources(tmp_path / "cache"))._vegetation(59.91, 10.75, str(cover), "2026-10-26T00:00:00Z")
    assert result["tree_cover_percent"] is None
    assert result["valid_fraction"] == 0
    assert source["status"] == "unavailable"


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")], ids=["nan", "positive_inf", "negative_inf"])
def test_nonfinite_scalar_pixels_stay_unknown_in_serializable_route_context(tmp_path, monkeypatch, invalid):
    import json
    from apps.api.route_context import RouteContext

    urls = {}
    for name in ("sand", "silt", "clay", "terrain", "worldcover"):
        path = tmp_path / f"{name}.tif"
        _raster(path, np.full((3, 3), 30 if name == "worldcover" else invalid))
        urls[name] = str(path)
    static = StaticSources(tmp_path / "cache")
    monkeypatch.setattr(static, "_urls_for_point", lambda *_: urls)
    plan = {"analysis_kind": "terrain_transect", "request": {"trip_date": "2026-10-26"},
            "routes": [{"id": "transect-1", "geometry": {"type": "LineString", "coordinates": [[10.74, 59.90], [10.76, 59.92]]}}]}
    result = RouteContext().build(plan, {"plan_id": "a" * 32, "route_id": "transect-1", "section_index": 1}, static, None)
    json.dumps(result, allow_nan=False)
    assert result["status"] == "partial"
    assert result["ground_composition"]["status"] == "unavailable"
    assert result["ground_composition"]["composition"] == {"sand": None, "silt": None, "clay": None}
    assert result["terrain"]["elevation_m"] is None and result["local_terrain"]["slope_deg"] is None
    assert result["land_cover"]["class"] == 30
    assert all(source["status"] == "unavailable" for source in result["sources"] if source["id"] in {"soilgrids", "copernicus-glo-30"})
