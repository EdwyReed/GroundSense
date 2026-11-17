"""Conservative native mosaic regressions: unknown never becomes mapped land."""
import numpy as np
import pytest
from rasterio.transform import from_origin

from apps.api.static_sources import StaticSources
from apps.api.terrain_grid import TerrainGridSource
from tests.runtime_routes.test_terrain_grid import raster


@pytest.mark.parametrize('code', [0, 10, 50, 70, 80, 255])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('coarsen', [False, True])
def test_overlap_unknown_excluded_or_conflicting_class_stays_blocked(tmp_path, code, reverse, coarsen):
    transform = from_origin(0, 16, 1, 1)
    cover = np.full((16, 16), 30, dtype='uint8')
    cover[8, 8] = code
    first = raster(tmp_path / 'first.tif', cover, transform=transform)
    second = raster(tmp_path / 'second.tif', np.full((16, 16), 30, dtype='uint8'), transform=transform)
    dem = raster(tmp_path / 'dem.tif', np.ones((16, 16), dtype='float32'), transform=transform, nodata=-9999)
    source = TerrainGridSource(StaticSources(tmp_path / 'cache'))
    if coarsen:
        source.MAX_GRID_CELLS = 64
    urls = tuple(str(path) for path in ((second, first) if reverse else (first, second)))
    grid = source._read((0, 0, 16, 16), urls, (str(dem),))
    row, col = grid.cell_at({'longitude': 8.5, 'latitude': 7.5})
    assert grid.costs[row][col] is None
    row, col = grid.cell_at({'longitude': 2.5, 'latitude': 13.5})
    assert grid.costs[row][col] == 1.0


def test_adjacent_tiles_have_no_false_unknown_seam_and_agreement_is_known(tmp_path):
    cover = np.full((16, 16), 30, dtype='uint8')
    west = raster(tmp_path / 'west.tif', cover, transform=from_origin(0, 16, 1, 1))
    east = raster(tmp_path / 'east.tif', cover, transform=from_origin(16, 16, 1, 1))
    dem = raster(tmp_path / 'dem.tif', np.ones((16, 32), dtype='float32'), transform=from_origin(0, 16, 1, 1), nodata=-9999)
    source = TerrainGridSource(StaticSources(tmp_path / 'cache'))
    grid = source._read((0, 0, 32, 16), (str(west), str(west), str(east)), (str(dem),))
    assert grid.costs[8][15] == grid.costs[8][16] == 1.0
