"""Bounded area grids for heuristic off-road candidate search, not mobility.

WorldCover exclusions and costs are versioned planning choices. DSM relief is
not bare-earth slope; neither product proves current water, clearance or access.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import math
import threading
from time import monotonic
from typing import Any, cast

from apps.api.route_planner import RoutePlanner
from apps.api.static_sources import StaticSources

COVER_CODES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)


class GridUnavailable(ValueError):
    """A bounded, safe-to-display failure, never an all-open fallback."""


@dataclass(frozen=True)
class TerrainGrid:
    costs: tuple[tuple[float | None, ...], ...]
    elevations: tuple[tuple[float | None, ...], ...]
    transform: tuple[float, ...]
    cell_size_m: tuple[float, float]
    source: dict[str, Any]
    cover_masks: tuple[tuple[int, ...], ...] = ()

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.costs), len(self.costs[0])

    def cell_at(self, point: dict[str, Any]) -> tuple[int, int]:
        lon = StaticSources._coordinate(point.get('longitude'), 'longitude', -180, 180)
        lat = StaticSources._coordinate(point.get('latitude'), 'latitude', -90, 90)
        a, _, x, _, e, y = self.transform
        row, col = math.floor((lat - y) / e), math.floor((lon - x) / a)
        if not (0 <= row < self.shape[0] and 0 <= col < self.shape[1]):
            raise ValueError('Point outside search grid; snapping is not permitted.')
        return row, col

    def path_to_coordinates(self, path: tuple[tuple[int, int], ...], origin: dict[str, Any], destination: dict[str, Any]) -> list[list[float]]:
        if not path or len(path) > 65_536 or path[0] != self.cell_at(origin) or path[-1] != self.cell_at(destination):
            raise ValueError('Path does not bind to requested endpoints.')
        for index, (row, col) in enumerate(path):
            if type(row) is not int or type(col) is not int or not (0 <= row < self.shape[0] and 0 <= col < self.shape[1]) or self.costs[row][col] is None:
                raise ValueError('Path crosses an excluded cell.')
            if index:
                r0, c0 = path[index - 1]
                dr, dc = row - r0, col - c0
                if max(abs(dr), abs(dc)) != 1 or (dr and dc and (self.costs[r0][col] is None or self.costs[row][c0] is None)):
                    raise ValueError('Path has a jump or cuts an excluded corner.')
        # Remove only exactly collinear grid steps, never a shortcut or smoothing.
        retained = [path[0]]
        for index in range(1, len(path) - 1):
            before, here, after = path[index - 1:index + 2]
            if (here[0] - before[0], here[1] - before[1]) != (after[0] - here[0], after[1] - here[1]):
                retained.append(here)
        if path[-1] != retained[-1]:
            retained.append(path[-1])
        a, _, x, _, e, y = self.transform
        coords = [[origin['longitude'], origin['latitude']]]
        coords.extend([[x + (col + .5) * a, y + (row + .5) * e] for row, col in retained])
        coords.append([destination['longitude'], destination['latitude']])
        coords = [point for index, point in enumerate(coords) if index == 0 or point != coords[index - 1]]
        if len(coords) > 256:
            raise GridUnavailable('geometry budget exceeded; no simplified substitute')
        distance = sum(RoutePlanner._distance_m({'longitude': a[0], 'latitude': a[1]}, {'longitude': b[0], 'latitude': b[1]}) for a, b in zip(coords, coords[1:]))
        if not 0 < distance <= 20_000:
            raise GridUnavailable('path length budget exceeded')
        return coords


class TerrainGridSource:
    MAX_NATIVE_PIXELS: int = 4_000_000
    MAX_GRID_CELLS: int = 65_536
    MAX_GRID_AXIS = 512
    MAX_TILES_PER_PRODUCT = 4
    POLICY = 'worldcover-dsm-preliminary-v1'
    # Relative authored preferences, not measured mobility/cost/soil parameters.
    COSTS = {10: 1.4, 20: 1.3, 30: 1.0, 40: 1.2, 60: 1.3, 90: 5.0, 95: 5.0, 100: 1.5}
    EXCLUDED = (50, 70, 80)
    ENV = {'GDAL_DISABLE_READDIR_ON_OPEN': 'EMPTY_DIR', 'CPL_VSIL_CURL_ALLOWED_EXTENSIONS': '.tif,.vrt',
           'CPL_VSIL_CURL_CACHE_SIZE': str(2 * 1024 * 1024), 'GDAL_HTTP_MAX_RETRY': '0', 'GDAL_HTTP_TIMEOUT': '15', 'GDAL_CACHEMAX': 16 * 1024 * 1024}

    def __init__(self, adapter: StaticSources, *, padding_m: float = 500) -> None:
        if type(padding_m) not in (int, float) or not math.isfinite(padding_m) or not 1 <= padding_m <= 5000:
            raise ValueError('Invalid search padding.')
        self.adapter, self.padding_m = adapter, float(padding_m)
        self._lock = threading.Lock()
        self._cache: OrderedDict[Any, tuple[float, TerrainGrid]] = OrderedDict()

    def read(self, origin: dict[str, Any], destination: dict[str, Any]) -> TerrainGrid:
        bounds = self._bounds(origin, destination)
        west, south, east, north = bounds
        urls = [self.adapter._urls_for_point(lat, lon) for lon in (west, east) for lat in (south, north)]
        cover_urls = tuple(sorted({row['worldcover'] for row in urls if isinstance(row.get('worldcover'), str)}))
        dem_urls = tuple(sorted({row['terrain'] for row in urls if isinstance(row.get('terrain'), str)}))
        if not cover_urls or not dem_urls or max(len(cover_urls), len(dem_urls)) > self.MAX_TILES_PER_PRODUCT:
            raise GridUnavailable('approved source tile budget or availability failure')
        key = (bounds, cover_urls, dem_urls, self.MAX_NATIVE_PIXELS, self.MAX_GRID_CELLS)
        with self._lock:
            cached = self._cache.get(key)
            if cached and monotonic() - cached[0] <= 300:
                self._cache.move_to_end(key)
                return deepcopy(cached[1])
            try:
                result = self._read(bounds, cover_urls, dem_urls)
            except GridUnavailable:
                raise
            except Exception as exc:
                raise GridUnavailable('approved area rasters temporarily unavailable') from exc
            self._cache[key] = (monotonic(), result)
            self._cache.move_to_end(key)
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
            return deepcopy(result)

    def _bounds(self, origin: dict[str, Any], destination: dict[str, Any]) -> tuple[float, float, float, float]:
        values = []
        for point in (origin, destination):
            lon = self.adapter._coordinate(point.get('longitude'), 'longitude', -180, 180)
            lat = self.adapter._coordinate(point.get('latitude'), 'latitude', -75, 75)
            values.append((lon, lat))
        distance = RoutePlanner._distance_m(origin, destination)
        if not 1 <= distance <= 20_000 or abs(values[0][0] - values[1][0]) > 180:
            raise ValueError('Candidate search supports endpoints 1 m to 20 km apart, without antimeridian crossing.')
        lon_margin = self.padding_m / (111_320 * math.cos(math.radians((values[0][1] + values[1][1]) / 2)))
        lat_margin = self.padding_m / 111_320
        bounds = (min(p[0] for p in values) - lon_margin, min(p[1] for p in values) - lat_margin,
                  max(p[0] for p in values) + lon_margin, max(p[1] for p in values) + lat_margin)
        if bounds[0] < -180 or bounds[2] > 180:
            raise ValueError('Search extent crosses the antimeridian.')
        return bounds

    def _read(self, bounds, cover_urls, dem_urls) -> TerrainGrid:
        import numpy as np
        import rasterio
        from affine import Affine
        from rasterio.enums import Resampling
        from rasterio.merge import merge
        from rasterio.vrt import WarpedVRT
        from rasterio.warp import transform_bounds

        retrieved = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        with rasterio.Env(**self.ENV), ExitStack() as stack:
            covers = [stack.enter_context(rasterio.open(url)) for url in cover_urls]
            reference = covers[0].transform
            for ds in covers:
                t = ds.transform
                if ds.crs is None or ds.crs.to_string() != 'EPSG:4326' or not all(math.isfinite(v) for v in t[:6]) or t.b or t.d or t.a <= 0 or t.e >= 0 or not math.isclose(t.a, reference.a) or not math.isclose(t.e, reference.e) or ds.scales[0] != 1 or ds.offsets[0] != 0 or ds.dtypes[0] != 'uint8':
                    raise GridUnavailable('unsupported WorldCover raster metadata')
                if any(abs(value - round(value)) > 1e-6 for value in ((t.c - reference.c) / reference.a, (t.f - reference.f) / reference.e)):
                    raise GridUnavailable('WorldCover tiles have different pixel phases')
            left = math.floor((bounds[0] - reference.c) / reference.a)
            right = math.ceil((bounds[2] - reference.c) / reference.a)
            top = math.floor((bounds[3] - reference.f) / reference.e)
            bottom = math.ceil((bounds[1] - reference.f) / reference.e)
            aligned = (reference.c + left * reference.a, reference.f + bottom * reference.e,
                       reference.c + right * reference.a, reference.f + top * reference.e)
            # Bound native allocation before merge reads, not after materializing.
            width, height = right - left, bottom - top
            if width * height > self.MAX_NATIVE_PIXELS:
                raise GridUnavailable('native area pixel budget exceeded')
            def conservative_merge(merged_data, new_data, merged_mask, new_mask, **kwargs):
                # 65535 means not yet covered, unlike a real native unknown (0).
                # Native masks apply inside the intersected source footprint.
                # Once unknown/conflicting, a pixel cannot be filled by a later
                # tile, regardless of source order. Agreement remains mapped.
                fresh = merged_data == 65535
                incoming = np.where(new_mask, 0, np.ma.getdata(new_data))
                np.copyto(merged_data, 0, where=~fresh & (merged_data != incoming))
                np.copyto(merged_data, incoming, where=fresh)

            mosaic, native_transform = merge(covers, bounds=aligned, res=(reference.a, -reference.e),
                                             nodata=65535, dtype='uint16', indexes=[1], method=cast(Any, conservative_merge))
            native = np.where(mosaic[0] == 65535, 0, mosaic[0]).astype('uint8')
            factor = 1
            while math.ceil(native.shape[0] / factor) * math.ceil(native.shape[1] / factor) > self.MAX_GRID_CELLS or max(math.ceil(native.shape[0] / factor), math.ceil(native.shape[1] / factor)) > self.MAX_GRID_AXIS:
                factor += 1
            rows, cols = math.ceil(native.shape[0] / factor), math.ceil(native.shape[1] / factor)
            padded = np.zeros((rows * factor, cols * factor), dtype='uint8')
            padded[:native.shape[0], :native.shape[1]] = native
            weights = np.full(padded.shape, np.nan)
            for code, cost in self.COSTS.items():
                weights[padded == code] = cost
            blocks = weights.reshape(rows, factor, cols, factor)
            # Preserve every native cover class in a coarse planning cell. Cost
            # alone cannot distinguish shrubland from bare/sparse vegetation.
            cover_bits = np.zeros(padded.shape, dtype='uint16')
            for bit, code in enumerate(COVER_CODES):
                cover_bits[padded == code] = 1 << bit
            cover_masks = np.bitwise_or.reduce(cover_bits.reshape(rows, factor, cols, factor), axis=(1, 3))
            valid = np.isfinite(blocks).all(axis=(1, 3))
            costs = np.where(valid, np.where(np.isfinite(blocks), blocks, 0).max(axis=(1, 3)), np.nan)
            # One search-cell buffer covers aggregation/native edge uncertainty.
            excluded = ~valid
            padded_excluded = np.pad(excluded, 1, constant_values=True)
            buffered = np.zeros_like(excluded)
            for dr in range(3):
                for dc in range(3):
                    buffered |= padded_excluded[dr:dr + rows, dc:dc + cols]
            costs[buffered] = np.nan
            grid_transform = native_transform * Affine.scale(factor)
            elevations = np.full((rows, cols), np.nan, dtype='float64')
            dem_records = []
            for url in dem_urls:
                ds = stack.enter_context(rasterio.open(url))
                if ds.crs is None or not math.isfinite(ds.scales[0]) or not math.isfinite(ds.offsets[0]):
                    raise GridUnavailable('unsupported DSM raster metadata')
                # Bound source-window support as well as the small output grid.
                native_bounds = transform_bounds('EPSG:4326', ds.crs, *bounds)
                if ds.transform.b or ds.transform.d or ds.transform.a <= 0 or ds.transform.e >= 0:
                    raise GridUnavailable('unsupported DSM affine')
                estimate = (math.ceil((native_bounds[2] - native_bounds[0]) / ds.transform.a) + 2) * (math.ceil((native_bounds[3] - native_bounds[1]) / -ds.transform.e) + 2)
                if estimate > self.MAX_NATIVE_PIXELS:
                    raise GridUnavailable('DSM area pixel budget exceeded')
                with WarpedVRT(ds, crs='EPSG:4326', transform=grid_transform, width=cols, height=rows, resampling=Resampling.nearest, dtype='float64', nodata=float('nan'), warp_mem_limit=16) as vrt:
                    raw = vrt.read(1, masked=True)
                    scaled = raw.data * ds.scales[0] + ds.offsets[0]
                    usable = ~np.ma.getmaskarray(raw) & np.isfinite(scaled) & (np.abs(scaled) <= 1e6) & ~np.isfinite(elevations)
                    elevations[usable] = scaled[usable]
                dem_records.append({'url': url, 'crs': ds.crs.to_string(), 'transform': list(ds.transform)[:6], 'scale': ds.scales[0], 'offset': ds.offsets[0]})
            costs[~np.isfinite(elevations)] = np.nan
            centre_lat = (bounds[1] + bounds[3]) / 2
            dx = RoutePlanner._distance_m({'longitude': bounds[0], 'latitude': centre_lat}, {'longitude': bounds[0] + grid_transform.a, 'latitude': centre_lat})
            dy = RoutePlanner._distance_m({'longitude': bounds[0], 'latitude': centre_lat}, {'longitude': bounds[0], 'latitude': centre_lat + grid_transform.e})
            def digest(array):
                return hashlib.sha256(array.tobytes(order='C')).hexdigest()
            details = {'policy': self.POLICY, 'cost_basis': 'authored relative preferences, not calibrated vehicle response',
                       'mosaic_policy': 'agreement_only_unknown_dominates_v1',
                       'costs': {str(k): v for k, v in self.COSTS.items()}, 'excluded_classes': list(self.EXCLUDED), 'unknown_policy': 'excluded',
                       'barrier_buffer_cells': 1, 'bounds_wgs84': list(bounds), 'aligned_native_bounds_wgs84': list(aligned), 'shape': [rows, cols], 'native_shape': list(native.shape),
                       'transform': list(grid_transform)[:6], 'native_transform': list(native_transform)[:6], 'aggregation_factor': factor,
                       'cell_size_m': [dx, dy], 'static_reference_year': 2021, 'surface_kind': 'DSM', 'date_used': False, 'vehicle_used': False,
                       'native_worldcover_sha256': digest(native), 'cover_mask_legend': list(COVER_CODES), 'cover_grid_sha256': digest(cover_masks.astype('<u2')),
                       'cost_grid_sha256': digest(costs.astype('<f8')), 'dsm_grid_sha256': digest(elevations.astype('<f8')),
                       'excluded_cells': int((~np.isfinite(costs)).sum()), 'dsm_tiles': dem_records,
                       'limitations': ['Static mapped water/buildings/snow excluded by planning policy, not current observations.', 'DSM includes trees and structures, not bare-earth slope.', 'No tree clearance, soil bearing, current flooding, transport suitability or recovery inference.']}
            evidence_urls = {f'{kind}_{index}': url for kind, urls in (('worldcover', cover_urls), ('terrain', dem_urls)) for index, url in enumerate(urls)}
            evidence = self.adapter._store_evidence('terrain-search-grid', evidence_urls, [details], retrieved)
            source = {'id': 'terrain-search-grid', 'product': 'ESA WorldCover 2021 v200 + Copernicus GLO-30 DSM', 'retrieved_at': retrieved,
                      'content_sha256': evidence, 'extraction_scope': 'bounded_area_grid', 'data': details}
            values = lambda array: tuple(tuple(float(v) if math.isfinite(float(v)) else None for v in row) for row in array)
            return TerrainGrid(values(costs), values(elevations), tuple(grid_transform)[:6], (dx, dy), source,
                               tuple(tuple(int(v) for v in row) for row in cover_masks))
