"""Local native-raster tests, not claims about field mobility."""
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from apps.api.static_sources import StaticSources
from apps.api.terrain_grid import TerrainGridSource, GridUnavailable


A = {'longitude': 10.002, 'latitude': 60.002}
B = {'longitude': 10.003, 'latitude': 60.003}


def raster(path, data, *, transform=None, crs='EPSG:4326', nodata=0):
    with rasterio.open(path, 'w', driver='GTiff', width=data.shape[1], height=data.shape[0], count=1, dtype=data.dtype, crs=crs,
                       transform=transform or from_origin(10, 60.00533333333333, 1 / 12000, 1 / 12000), nodata=nodata) as ds:
        ds.write(data, 1)
    return path


class LocalSources(StaticSources):
    def __init__(self, tmp_path, cover=None, heights=None):
        super().__init__(tmp_path / 'evidence-cache')
        self.cover = raster(tmp_path / 'cover.tif', np.full((64, 64), 30, dtype='uint8') if cover is None else cover)
        self.dem = raster(tmp_path / 'dsm.tif', np.full((64, 64), 150, dtype='float32') if heights is None else heights, nodata=-9999)

    def _urls_for_point(self, latitude, longitude):
        return {'worldcover': str(self.cover), 'terrain': str(self.dem)}


def test_reads_an_area_not_just_the_ab_line_and_binds_native_values(tmp_path):
    grid = TerrainGridSource(LocalSources(tmp_path), padding_m=30).read(A, B)
    rows, cols = grid.shape
    assert rows > 2 and cols > 2
    assert grid.costs[grid.cell_at(A)[0]][grid.cell_at(A)[1]] == 1
    assert grid.elevations[grid.cell_at(B)[0]][grid.cell_at(B)[1]] == 150
    assert grid.source['content_sha256'].startswith('sha256:')
    assert grid.source['data']['native_worldcover_sha256']
    assert grid.source['data']['surface_kind'] == 'DSM'
    assert grid.source['data']['vehicle_used'] is False
    assert grid.source['data']['date_used'] is False
    assert grid.source['data']['unknown_policy'] == 'excluded'
    native = grid.source['data']['native_transform']
    assert abs((native[2] - 10) * 12000 - round((native[2] - 10) * 12000)) < 1e-6
    assert abs((native[5] - 60.00533333333333) * 12000 - round((native[5] - 60.00533333333333) * 12000)) < 1e-6
    assert all(value is None or value == 1 for row in grid.costs for value in row)


@pytest.mark.parametrize('code', [0, 50, 70, 80, 255])
def test_unknown_and_policy_excluded_classes_cannot_be_silently_traversed(tmp_path, code):
    cover = np.full((64, 64), 30, dtype='uint8'); cover[:, 30] = code
    grid = TerrainGridSource(LocalSources(tmp_path, cover), padding_m=30).read(A, B)
    row, col = grid.cell_at({'longitude': 10 + 30.5 / 12000, 'latitude': A['latitude']})
    assert grid.costs[row][col] is None


def test_thin_native_barrier_survives_coarsening(tmp_path):
    cover = np.full((64, 64), 30, dtype='uint8'); cover[:, 30] = 80
    source = TerrainGridSource(LocalSources(tmp_path, cover), padding_m=30)
    source.MAX_GRID_CELLS = 64
    grid = source.read(A, B)
    assert grid.shape[0] * grid.shape[1] <= 64
    assert grid.source['data']['aggregation_factor'] > 1
    point = {'longitude': 10 + 30.5 / 12000, 'latitude': (A['latitude'] + B['latitude']) / 2}
    row, col = grid.cell_at(point)
    assert grid.costs[row][col] is None
    (tmp_path / 'control').mkdir()
    control = TerrainGridSource(LocalSources(tmp_path / 'control'), padding_m=30)
    control.MAX_GRID_CELLS = 64
    clean = control.read(A, B)
    assert clean.costs[row][col] == 1


@pytest.mark.parametrize('value', [-9999, float('nan'), float('inf')])
def test_missing_or_nonfinite_dsm_excludes_cells(tmp_path, value):
    heights = np.full((64, 64), value, dtype='float32')
    grid = TerrainGridSource(LocalSources(tmp_path, heights=heights), padding_m=30).read(A, B)
    assert all(value is None for row in grid.costs for value in row)


def test_resource_bound_rejects_before_large_native_read(tmp_path):
    source = TerrainGridSource(LocalSources(tmp_path), padding_m=30)
    source.MAX_NATIVE_PIXELS = 1
    with pytest.raises(GridUnavailable, match='budget'):
        source.read(A, B)


def test_unknown_source_does_not_make_an_all_open_grid(tmp_path):
    adapter = LocalSources(tmp_path); adapter.cover.unlink()
    with pytest.raises(GridUnavailable):
        TerrainGridSource(adapter, padding_m=30).read(A, B)


def test_coordinates_keep_real_endpoints_and_do_not_clamp_external_points(tmp_path):
    grid = TerrainGridSource(LocalSources(tmp_path), padding_m=30).read(A, B)
    start = grid.cell_at(A)
    end = (start[0], start[1] + 1)
    x0, y0 = grid.transform[2], grid.transform[5]
    destination = {'longitude': x0 + (end[1] + .5) * grid.transform[0], 'latitude': y0 + (end[0] + .5) * grid.transform[4]}
    path = grid.path_to_coordinates((start, end), A, destination)
    assert path[0] == [A['longitude'], A['latitude']]
    assert path[-1] == [destination['longitude'], destination['latitude']]
    with pytest.raises(ValueError):
        grid.cell_at({'longitude': 11, 'latitude': 60})
    with pytest.raises(ValueError):
        grid.path_to_coordinates((start, (start[0] + 3, start[1])), A, destination)


@pytest.mark.parametrize('point', [dict(A, latitude=True), dict(A, latitude=float('nan')), dict(A, latitude=80), dict(A, longitude=180)])
def test_invalid_or_unsupported_region_is_rejected_before_io(tmp_path, point):
    adapter = LocalSources(tmp_path)
    def reject(latitude: float, longitude: float) -> dict[str, str]:
        pytest.fail('network selection before validation')
    adapter._urls_for_point = reject
    with pytest.raises(ValueError):
        TerrainGridSource(adapter).read(point, B)
