from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("rasterio")
from rasterio.transform import from_origin

from apps.api.static_sources import StaticSources


def _raster(path: Path, value: int, *, nodata: int | None = None, tags: dict[str, str] | None = None) -> None:
    import numpy as np
    import rasterio

    with rasterio.open(
        path, "w", driver="GTiff", width=3, height=3, count=1, dtype="int16",
        crs="EPSG:4326", transform=from_origin(10.70, 59.95, 0.02, 0.02), nodata=nodata,
    ) as dataset:
        dataset.write(np.full((1, 3, 3), value, dtype="int16"))
        if tags:
            dataset.update_tags(**tags)


@pytest.mark.parametrize('offset', [5.0, float('nan'), float('inf')])
def test_scalar_sample_applies_finite_native_offset(tmp_path, offset):
    import math
    import rasterio

    path = tmp_path / 'offset.tif'
    _raster(path, -3)
    with rasterio.open(path, 'r+') as dataset:
        dataset.scales = (2.0,)
        dataset.offsets = (offset,)
    sample, _ = StaticSources(tmp_path / 'cache')._sample(str(path), 59.91, 10.75)
    if math.isfinite(offset):
        assert sample is not None
        assert sample['value'] == -1
        assert sample['offset'] == 5
    else:
        assert sample is None


def test_read_returns_contract_shape_and_preserves_raster_metadata(tmp_path, monkeypatch):
    """A source result only becomes available after a raster pixel was actually read."""
    files = {}
    for name, value, tags in (
        ("sand", 410, {"units": "g/kg", "depth": "0-5cm", "statistic": "Q0.5", "scale_factor": "1"}),
        ("sand_q05", 350, {"units": "g/kg", "depth": "0-5cm", "statistic": "Q0.05", "scale_factor": "1"}),
        ("sand_q95", 470, {"units": "g/kg", "depth": "0-5cm", "statistic": "Q0.95", "scale_factor": "1"}),
        ("silt", 380, {"units": "g/kg", "depth": "0-5cm", "statistic": "Q0.5", "scale_factor": "1"}),
        ("silt_q05", 330, {"units": "g/kg", "depth": "0-5cm", "statistic": "Q0.05", "scale_factor": "1"}),
        ("silt_q95", 430, {"units": "g/kg", "depth": "0-5cm", "statistic": "Q0.95", "scale_factor": "1"}),
        ("clay", 210, {"units": "g/kg", "depth": "0-5cm", "statistic": "Q0.5", "scale_factor": "1"}),
        ("clay_q05", 180, {"units": "g/kg", "depth": "0-5cm", "statistic": "Q0.05", "scale_factor": "1"}),
        ("clay_q95", 240, {"units": "g/kg", "depth": "0-5cm", "statistic": "Q0.95", "scale_factor": "1"}),
        ("terrain", 123, {"units": "m", "vertical_datum": "EGM2008"}),
        ("worldcover", 40, {"units": "class", "product_version": "v200"}),
    ):
        path = tmp_path / f"{name}.tif"
        _raster(path, value, tags=tags)
        files[name] = str(path)

    sources = StaticSources(tmp_path / "cache")
    monkeypatch.setattr(sources, "_urls_for_point", lambda *_: files)

    result = sources.read(59.91, 10.75)

    assert set(result) == {"soil", "terrain", "land_cover", "sources"}
    assert result["soil"]["composition"] == {"sand": 41.0, "silt": 38.0, "clay": 21.0}
    row = result["soil"]["depths"][0]
    assert row["top_cm"] == 0 and row["bottom_cm"] == 5
    assert row["sand_g_kg"] == 410.0
    assert row["sand_uncertainty_90"] == {"lower": 350.0, "upper": 470.0, "unit": "g/kg"}
    assert row["metadata"]["scale_factor"] == 1.0
    assert result["terrain"]["elevation_m"] == 123.0
    assert result["terrain"]["surface_kind"] == "DSM"
    assert result["land_cover"]["class"] == 40
    assert result["land_cover"]["label"] == "cropland"
    for source in result["sources"]:
        assert source["status"] == "available"
        assert source["content_sha256"].startswith("sha256:")
        assert source["retrieved_at"]

    evidence = list((tmp_path / "cache" / "evidence").glob("*.json"))
    assert len(evidence) == 3
    payload = json.loads(evidence[0].read_text())
    samples = payload["sample"] if isinstance(payload["sample"], list) else [payload["sample"]]
    assert all(item["sample"]["window"]["width"] <= 3 for item in samples)


def test_read_returns_unknown_for_nodata_and_unavailable_source(tmp_path, monkeypatch):
    sources = StaticSources(tmp_path / "cache")
    monkeypatch.setattr(sources, "_urls_for_point", lambda *_: {"sand": str(tmp_path / "missing.tif")})

    result = sources.read(59.91, 10.75)

    assert result["soil"]["composition"] == {"sand": None, "silt": None, "clay": None}
    assert result["soil"]["support_m"] is None
    assert result["terrain"]["elevation_m"] is None
    assert result["land_cover"]["class"] is None
    assert {source["status"] for source in result["sources"]} == {"unavailable"}
    assert all(source["content_sha256"] is None for source in result["sources"])


@pytest.mark.parametrize('latitude,wc_tile', [(60.0, 'N57'), (60.0001, 'N60')])
def test_latitude_tile_selection_matches_native_north_south_footprints(tmp_path, latitude, wc_tile):
    urls = StaticSources(tmp_path / 'cache')._urls_for_point(latitude, 10.75)
    # Live GLO-30 N60 has bottom=60.00013888888889, not 60.0.
    # WorldCover is north-inclusive/south-exclusive: exactly 60 is in N57.
    assert 'Copernicus_DSM_COG_10_N59_00_E010' in urls['terrain']
    assert f'2021_v200_{wc_tile}E009_Map.tif' in urls['worldcover']


def test_fixed_approved_urls_choose_oslo_tiles_only(tmp_path):
    sources = StaticSources(tmp_path / "cache")

    urls = sources._urls_for_point(59.91, 10.75)

    assert set(urls) >= {"sand", "sand_q05", "sand_q95", "terrain", "worldcover"}
    assert all(url.startswith("https://") for url in urls.values())
    assert "Copernicus_DSM_COG_10_N59_00_E010_00_DEM" in urls["terrain"]
    assert "ESA_WorldCover_10m_2021_v200_N57E009_Map.tif" in urls["worldcover"]
    assert all("{" not in url and ".." not in url for url in urls.values())


def test_point_is_transformed_to_the_raster_crs_before_sampling(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.warp import transform

    x, y = transform("EPSG:4326", "EPSG:3857", [10.75], [59.91])
    path = tmp_path / "projected.tif"
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1,
                       dtype="int16", crs="EPSG:3857",
                       transform=from_origin(x[0]-125, y[0]+125, 250, 250)) as ds:
        ds.write(np.array([[[410, 1], [2, 3]]], dtype="int16"))
        ds.update_tags(units="g/kg")
    sample, reason = StaticSources(tmp_path / "cache")._sample(str(path), 59.91, 10.75)
    assert reason is None
    assert sample is not None
    assert sample["value"] == 410
    assert sample["crs"] == "EPSG:3857"
    assert sample["sample"]["row"] == sample["sample"]["column"] == 0


def test_soil_uses_explicit_publisher_units_when_the_vrt_has_empty_unit_tags(tmp_path, monkeypatch):
    paths = {}
    for name, value in [("sand", 410), ("silt", 380), ("clay", 210)]:
        path = tmp_path / f"{name}.tif"
        _raster(path, value)
        paths[name] = str(path)
    adapter = StaticSources(tmp_path / "cache")
    monkeypatch.setattr(adapter, "_urls_for_point", lambda *_: paths)
    result = adapter.read(59.91, 10.75)
    assert result["soil"]["composition"] == {"sand": 41.0, "silt": 38.0, "clay": 21.0}
    assert result["soil"]["composition_depth_cm"] == [0, 5]
    assert "docs.isric.org" in result["soil"]["depths"][0]["metadata"]["unit_source"]


def test_static_context_reuses_fresh_point_reads(tmp_path, monkeypatch):
    adapter = StaticSources(tmp_path / "cache")
    calls = []
    def sample(*args):
        calls.append(args)
        return None, "unit test: no upstream value"
    monkeypatch.setattr(adapter, "_sample", sample)
    first = adapter.read(59.91, 10.75)
    count = len(calls)
    first["soil"]["composition"]["sand"] = 999
    second = adapter.read(59.91, 10.75)
    assert len(calls) == count
    assert second["soil"]["composition"]["sand"] is None


def test_independent_texture_estimates_keep_original_values_and_expose_nonclosure(tmp_path, monkeypatch):
    paths = {}
    for name, value in [("sand", 426), ("silt", 337), ("clay", 79)]:
        path = tmp_path / f"{name}.tif"
        _raster(path, value, tags={"units": "g/kg", "statistic": "Q0.5"})
        paths[name] = str(path)
        paths[name + "_q05"] = str(path)
        paths[name + "_q95"] = str(path)
    adapter = StaticSources(tmp_path / "cache")
    monkeypatch.setattr(adapter, "_urls_for_point", lambda *_: paths)
    result = adapter.read(59.91, 10.75)
    assert result["soil"]["composition"] == {"sand": 42.6, "silt": 33.7, "clay": 7.9}
    source = next(row for row in result["sources"] if row["id"] == "soilgrids")
    assert source["status"] == source["qc"] == "partial"
    assert result["soil"]["depths"][0]["status"] == "partial"
    check = source["data"]["texture_closure"]
    assert check["total_percent"] == pytest.approx(84.2)
    assert check["within_tolerance"] is False and check["normalized"] is False
    assert "100%" in source["note"]


@pytest.mark.parametrize("value,nodata,scale,expected", [
    (0.0, None, 1.0, 0.0),
    (-12.5, None, 1.0, -12.5),
    (1.0, float("nan"), 1.0, 1.0),
    (1.0, None, float("inf"), None),
    (1e30, None, 1e300, None),
], ids=["real_zero", "signed_height", "nan_nodata_metadata", "invalid_scale", "scale_overflow"])
def test_scalar_values_and_metadata_remain_strict_json_safe(tmp_path, value, nodata, scale, expected):
    import numpy as np
    import rasterio

    path = tmp_path / "scalar.tif"
    with rasterio.open(path, "w", driver="GTiff", width=3, height=3, count=1, dtype="float64",
                       crs="EPSG:4326", transform=from_origin(10.70, 59.95, 0.02, 0.02), nodata=nodata) as dataset:
        dataset.write(np.full((1, 3, 3), value))
        dataset.scales = (scale,)
    sample, reason = StaticSources(tmp_path / "cache")._sample(str(path), 59.91, 10.75)
    if expected is None:
        assert sample is None or sample["value"] is None
        assert reason is not None
    else:
        assert sample is not None and sample["value"] == expected
        assert reason is None
    json.dumps(sample, allow_nan=False)
