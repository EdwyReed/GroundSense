from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from apps.api.land_cover_trace import LandCoverTrace
from apps.api.static_sources import StaticSources


class LocalStaticSources(StaticSources):
    def __init__(self, cache_dir: Path, cover: Path) -> None:
        super().__init__(cache_dir)
        self.cover = str(cover)

    def _urls_for_point(self, latitude, longitude):
        return {"worldcover": self.cover}


def test_trace_finds_narrow_native_cell_between_sparse_points_and_is_strict_json(tmp_path):
    cover = tmp_path / "cover.tif"
    with rasterio.open(cover, "w", driver="GTiff", height=1, width=3, count=1, dtype="uint8", crs="EPSG:4326", transform=from_origin(10, 60.1, 0.1, 0.1), nodata=255) as dataset:
        dataset.write(np.array([[10, 80, 10]], dtype="uint8"), 1)
    adapter = LocalStaticSources(tmp_path / "cache", cover)

    result = LandCoverTrace().read(adapter, [[10.01, 60.05], [10.29, 60.05]], "2026-10-26T00:00:00Z")

    assert result["status"] == "available"
    assert result["evidence_scope"] == "intersected_raster_cells"
    assert result["coverage"] == "centerline_only"
    assert result["cell_count"] == 3
    assert result["tile_attempts"] == 1
    assert [segment["class_code"] for segment in result["segments"]] == [10, 80, 10]
    assert result["segments"][1]["label"] == "permanent_water"
    assert result["known_m"] + result["unknown_m"] == pytest.approx(result["distance_m"])
    assert result["segments"][0]["geometry"]["coordinates"][0] == [10.01, 60.05]
    assert result["segments"][-1]["geometry"]["coordinates"][-1] == [10.29, 60.05]
    json.dumps(result, allow_nan=False)


import pytest


def test_cell_budget_keeps_unread_tail_unknown_and_geometrically_complete(tmp_path):
    cover = tmp_path / 'budget.tif'
    with rasterio.open(cover, 'w', driver='GTiff', height=1, width=3, count=1, dtype='uint8', crs='EPSG:4326', transform=from_origin(10, 60.1, .1, .1), nodata=255) as dataset:
        dataset.write(np.array([[10, 80, 30]], dtype='uint8'), 1)
    reader = LandCoverTrace()
    reader.MAX_CELL_SPANS = 1
    result = reader.read(LocalStaticSources(tmp_path / 'cache', cover), [[10.01, 60.05], [10.29, 60.05]], '2026-10-26T00:00:00Z')
    assert result['status'] == 'partial'
    assert result['cell_count'] <= 1
    assert 0 < result['known_m'] < result['distance_m']
    assert result['unknown_m'] > 0
    assert [row['class_code'] for row in result['segments']] == [10, None]
    assert result['segments'][-1]['geometry']['coordinates'][-1] == [10.29, 60.05]
    for left, right in zip(result['segments'], result['segments'][1:]):
        assert left['end_m'] == pytest.approx(right['start_m'])
        assert left['geometry']['coordinates'][-1] == right['geometry']['coordinates'][0]


def test_source_digest_binds_native_cell_values_not_just_grid_metadata(tmp_path):
    cover = tmp_path / 'values.tif'
    with rasterio.open(cover, 'w', driver='GTiff', height=1, width=2, count=1, dtype='uint8', crs='EPSG:4326', transform=from_origin(10, 60.1, .1, .1), nodata=255) as dataset:
        dataset.write(np.array([[10, 80]], dtype='uint8'), 1)
    adapter = LocalStaticSources(tmp_path / 'cache', cover)
    first = LandCoverTrace().read(adapter, [[10.01, 60.05], [10.19, 60.05]], '2026-10-26T00:00:00Z')
    with rasterio.open(cover, 'r+') as dataset:
        dataset.write(np.array([[10, 30]], dtype='uint8'), 1)
    second = LandCoverTrace().read(adapter, [[10.01, 60.05], [10.19, 60.05]], '2026-10-26T00:00:00Z')
    assert first['sources'][0]['content_sha256'] != second['sources'][0]['content_sha256']
    for receipt in adapter._evidence_dir.glob('*.json'):
        payload = json.loads(receipt.read_text())
        json.dumps(payload, allow_nan=False)
        assert all('raw_value' in sample and 'value' in sample for sample in payload['sample'])


def test_outside_prefix_does_not_erase_known_cells_from_the_same_tile(tmp_path):
    cover = tmp_path / 'edges.tif'
    with rasterio.open(cover, 'w', driver='GTiff', height=1, width=2, count=1, dtype='uint8', crs='EPSG:4326', transform=from_origin(10, 60.125, .0625, .125), nodata=255) as dataset:
        dataset.write(np.array([[10, 80]], dtype='uint8'), 1)
    result = LandCoverTrace().read(LocalStaticSources(tmp_path / 'cache', cover), [[9.98, 60.0625], [10.11, 60.0625]], '2026-10-26T00:00:00Z')
    assert result['status'] == 'partial'
    assert [row['class_code'] for row in result['segments']] == [None, 10, 80]
    assert result['known_m'] > 0 and result['unknown_m'] > 0


def test_diagonal_corner_contacts_and_duplicate_vertices_add_no_false_cells(tmp_path):
    cover = tmp_path / 'diagonal.tif'
    cells = np.full((3, 3), 50, dtype='uint8')
    np.fill_diagonal(cells, [10, 80, 30])
    with rasterio.open(cover, 'w', driver='GTiff', height=3, width=3, count=1, dtype='uint8', crs='EPSG:4326', transform=from_origin(10, 60.1875, .0625, .0625), nodata=255) as dataset:
        dataset.write(cells, 1)
    result = LandCoverTrace().read(LocalStaticSources(tmp_path / 'cache', cover), [[10.03125, 60.15625], [10.03125, 60.15625], [10.15625, 60.03125]], '2026-10-26T00:00:00Z')
    assert result['cell_count'] == 3
    assert [row['class_code'] for row in result['segments']] == [10, 80, 30]
    assert result['unknown_m'] == 0


@pytest.mark.parametrize('limit', ['window', 'tile'])
def test_exhausted_window_or_tile_budget_keeps_a_contiguous_unknown_remainder(tmp_path, limit):
    paths = []
    for index, code in enumerate([10, 80]):
        path = tmp_path / f'tile-{index}.tif'
        with rasterio.open(path, 'w', driver='GTiff', height=1, width=2, count=1, dtype='uint8', crs='EPSG:4326', transform=from_origin(11.75 + index * .25, 60.125, .125, .125), nodata=255) as dataset:
            dataset.write(np.full((1, 2), code, dtype='uint8'), 1)
        paths.append(path)

    class Tiles(StaticSources):
        def _urls_for_point(self, latitude, longitude):
            return {'worldcover': str(paths[int(longitude >= 12)])}

    reader = LandCoverTrace()
    if limit == 'tile':
        reader.MAX_TILE_ATTEMPTS = 1
    else:
        reader.MAX_WINDOWS = 1
    result = reader.read(Tiles(tmp_path / 'cache'), [[11.9, 60.0625], [12.1, 60.0625]], '2026-10-26T00:00:00Z')
    assert result['status'] == 'partial'
    assert [row['class_code'] for row in result['segments']] == [10, None]
    assert result['segments'][0]['end_m'] == pytest.approx(result['segments'][1]['start_m'])
    assert result['segments'][-1]['end_m'] == pytest.approx(result['distance_m'])
    assert result['segments'][-1]['geometry']['coordinates'][-1] == [12.1, 60.0625]


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), float('-inf'), 0, 77, 80.5])
def test_invalid_native_cover_values_remain_explicit_unknown_in_finite_evidence(tmp_path, invalid):
    cover = tmp_path / 'invalid.tif'
    with rasterio.open(cover, 'w', driver='GTiff', height=1, width=2, count=1, dtype='float64', crs='EPSG:4326', transform=from_origin(10, 60.125, .0625, .125), nodata=0) as dataset:
        dataset.write(np.array([[10, invalid]], dtype='float64'), 1)
    adapter = LocalStaticSources(tmp_path / 'cache', cover)
    result = LandCoverTrace().read(adapter, [[10.01, 60.0625], [10.11, 60.0625]], '2026-10-26T00:00:00Z')
    assert [row['class_code'] for row in result['segments']] == [10, None]
    assert result['status'] == 'partial'
    json.dumps(result, allow_nan=False)
    for path in adapter._evidence_dir.glob('*.json'):
        json.dumps(json.loads(path.read_text()), allow_nan=False)
