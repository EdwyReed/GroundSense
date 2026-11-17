from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import threading

import httpx
import numpy as np
import pytest
import rasterio
from rasterio.errors import RasterioError
from rasterio.transform import from_origin

from apps.api.surface_profile import SurfaceProfile
from apps.api.surface_observation import SurfaceObservation


def fixture(tmp_path, values=(6, 9, 11, 5), *, nodata=0, metadata=None, transform=None):
    path = tmp_path / 'scl.tif'
    with rasterio.open(path, 'w', driver='GTiff', height=1, width=4, count=1, dtype='float32', crs='EPSG:3857', transform=transform or from_origin(1_110_000, 8_420_000, 10_000, 10_000), nodata=nodata) as ds:
        ds.write(np.array([values], dtype='float32'), 1)
    calls = []
    item = {'id': 'scene', 'collection': 'sentinel-2-l2a', 'properties': {'datetime': '2026-10-25T10:00:00Z'}, 'assets': {'scl': {'href': str(path), 'raster:bands': [metadata or {'scale': 1, 'offset': 0, 'nodata': nodata}]}}}
    payload = {'features': [item]}
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)
    adapter = SurfaceProfile(tmp_path / 'cache', transport=httpx.MockTransport(handler), clock=lambda: datetime(2026, 10, 26, 12, tzinfo=UTC))
    adapter._public_asset = lambda href: True
    points = [{'chainage_m': float(i * 100), 'point': {'latitude': 60.05, 'longitude': longitude}} for i, longitude in enumerate((10.01, 10.11, 10.19))]
    return adapter, points, calls, payload


@pytest.mark.parametrize('value,expected', [(0, None), (float('nan'), None), (float('inf'), None), (4.5, None), (12, None), (3, 3), (11, 11), (5, 5)])
def test_native_values_preserve_unknown_shadow_snow_and_real_classes(tmp_path, value, expected):
    adapter, points, _, _ = fixture(tmp_path, values=(6, value, 5, 9))
    summary, source = adapter.read_points(points, '2026-10-26')
    assert [sample['scl_class'] for sample in summary['samples']] == [6, expected, 5]
    assert source['data']['samples'] == summary['samples']
    raw = (adapter.evidence_dir / f'{source["content_sha256"].removeprefix("sha256:")}.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == summary['source_content_sha256'].removeprefix('sha256:')
    assert json.loads(raw) == source['data']
    json.dumps((summary, source), allow_nan=False)


@pytest.mark.parametrize('metadata', [{'scale': 2, 'offset': 0, 'nodata': 0}, {'scale': 1, 'offset': 1, 'nodata': 0}])
def test_nonidentity_categorical_scaling_keeps_all_samples_unknown(tmp_path, metadata):
    adapter, points, _, _ = fixture(tmp_path, metadata=metadata)
    summary, _ = adapter.read_points(points, '2026-10-26')
    assert all(sample['scl_class'] is None and sample['condition'] == 'unknown' for sample in summary['samples'])


@pytest.mark.parametrize('reader', ['profile', 'point'])
def test_native_nodata_is_honoured_when_asset_disagrees_and_mask_is_absent(tmp_path, monkeypatch, reader):
    adapter, points, _, payload = fixture(tmp_path, values=(6, 4, 5, 9), nodata=4, metadata={'scale': 1, 'offset': 0, 'nodata': 0})
    original = rasterio.open
    class WithoutMask:
        def __init__(self, ds): self.ds = ds
        def __getattr__(self, key): return getattr(self.ds, key)
        def __enter__(self): self.ds.__enter__(); return self
        def __exit__(self, *args): return self.ds.__exit__(*args)
        def read(self, *args, **kwargs):
            kwargs['masked'] = False
            return np.ma.array(self.ds.read(*args, **kwargs), mask=False)
    monkeypatch.setattr(rasterio, 'open', lambda *args, **kwargs: WithoutMask(original(*args, **kwargs)))
    if reader == 'profile':
        summary, _ = adapter.read_points(points, '2026-10-26')
        assert [sample['scl_class'] for sample in summary['samples']] == [6, None, 5]
    else:
        point_reader = SurfaceObservation(tmp_path / 'point-cache')
        point_reader._public_asset = lambda href: True
        assert point_reader._sample_scl(payload['features'][0], 60.05, 10.11)['raw_class'] is None


def test_one_native_read_failure_does_not_erase_other_points(tmp_path, monkeypatch):
    adapter, points, _, _ = fixture(tmp_path, values=(6, 4, 5, 9))
    original = rasterio.open
    opened, reads = [], []
    class Intermittent:
        def __init__(self, ds): self.ds = ds
        def __getattr__(self, key): return getattr(self.ds, key)
        def __enter__(self): self.ds.__enter__(); return self
        def __exit__(self, *args): return self.ds.__exit__(*args)
        def read(self, *args, **kwargs):
            reads.append(kwargs['window'])
            if len(reads) == 2: raise RasterioError('single-cell read failed')
            return self.ds.read(*args, **kwargs)
    def open_once(*args, **kwargs):
        opened.append(args)
        return Intermittent(original(*args, **kwargs))
    monkeypatch.setattr(rasterio, 'open', open_once)
    summary, _ = adapter.read_points(points, '2026-10-26')
    assert [sample['scl_class'] for sample in summary['samples']] == [6, None, 5]
    assert len(opened) == 1 and len(reads) == 3


@pytest.mark.parametrize('corruption', ['list-root', 'bad-properties', 'bad-assets', 'too-many'])
@pytest.mark.parametrize('reader', ['profile', 'point'])
def test_malformed_catalogue_is_local_unknown_without_unhandled_errors(tmp_path, corruption, reader):
    adapter, points, _, payload = fixture(tmp_path)
    if corruption == 'list-root':
        adapter.transport = httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
    elif corruption == 'bad-properties': payload['features'][0]['properties'] = ['bad']
    elif corruption == 'bad-assets': payload['features'][0]['assets'] = ['bad']
    else: payload['features'] *= 13
    if reader == 'profile':
        summary, _ = adapter.read_points(points, '2026-10-26')
        assert all(row['scl_class'] is None and row['condition'] == 'unknown' for row in summary['samples'])
    else:
        point_reader = SurfaceObservation(tmp_path / 'point-cache', transport=adapter.transport, clock=adapter._clock)
        point_reader._public_asset = lambda href: True
        summary, _ = point_reader.read_point(60.05, 10.01, '2026-10-26')
        assert summary['scl_class'] is None and summary['condition'] == 'unknown'


def test_exact_cache_is_deep_copied_date_point_bound_and_expires(tmp_path, monkeypatch):
    adapter, points, calls, _ = fixture(tmp_path)
    now = [0.0]
    monkeypatch.setattr('apps.api.surface_profile.time.monotonic', lambda: now[0])
    result = adapter.read_points(points, '2026-10-26')
    result[0]['samples'][0]['scl_class'] = 5
    result[1]['data']['samples'][0]['scl_class'] = 5
    assert adapter.read_points(points, '2026-10-26')[0]['samples'][0]['scl_class'] == 6
    assert len(calls) == 1
    adapter.read_points(points, '2026-10-27')
    changed = deepcopy(points); changed[0]['point']['longitude'] += 1e-10
    adapter.read_points(changed, '2026-10-26')
    assert len(calls) == 3
    now[0] = 301
    adapter.read_points(points, '2026-10-26')
    assert len(calls) == 4
    for i in range(18): adapter.read_points(points, (date(2026, 10, 26) + timedelta(days=i)).isoformat())
    assert adapter.cache_size == 16
    assert len(list(adapter.evidence_dir.glob('*.json'))) <= 16


def test_single_flight_prevents_concurrent_duplicate_catalogue_reads(tmp_path):
    adapter, points, calls, payload = fixture(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def handler(request):
        calls.append(request); entered.set()
        assert release.wait(5)
        return httpx.Response(200, json=payload)
    adapter.transport = httpx.MockTransport(handler)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(adapter.read_points, points, '2026-10-26')
        assert entered.wait(5)
        second = pool.submit(adapter.read_points, points, '2026-10-26')
        release.set()
        left, right = first.result(), second.result()
    assert len(calls) == 1 and left == right and left[0] is not right[0]


def test_future_candidate_is_rejected_against_one_captured_retrieval_instant(tmp_path):
    adapter, points, _, payload = fixture(tmp_path)
    future = deepcopy(payload['features'][0]); future['id'] = 'future'; future['properties']['datetime'] = '2026-10-26T12:00:00.500Z'
    payload['features'].append(future)
    summary, _ = adapter.read_points(points, '2026-11-01')
    assert summary['scene_id'] == 'scene' and summary['scene_age_days'] == 7


def test_outside_extent_stays_unknown_without_clamping(tmp_path):
    adapter, points, _, _ = fixture(tmp_path)
    points[-1]['point']['longitude'] = 12
    summary, source = adapter.read_points(points, '2026-10-26')
    assert [sample['scl_class'] for sample in summary['samples']] == [6, 9, None]
    assert source['data']['native_samples'][-1]['window'] is None


@pytest.mark.parametrize('count', [1, 82])
def test_point_cap_is_rejected_before_io(tmp_path, count):
    adapter, _, calls, _ = fixture(tmp_path)
    points = [{'chainage_m': float(i), 'point': {'latitude': 60.05, 'longitude': 10.01}} for i in range(count)]
    with pytest.raises(ValueError): adapter.read_points(points, '2026-10-26')
    assert not calls


def test_81_points_use_one_cog_and_no_more_than_81_one_cell_reads(tmp_path, monkeypatch):
    adapter, _, _, _ = fixture(tmp_path)
    points = [{'chainage_m': float(i * 125), 'point': {'latitude': 60.05, 'longitude': 10.01 + .18 * i / 80}} for i in range(81)]
    original = rasterio.open
    opened, windows = [], []
    class Counted:
        def __init__(self, ds): self.ds = ds
        def __getattr__(self, key): return getattr(self.ds, key)
        def __enter__(self): self.ds.__enter__(); return self
        def __exit__(self, *args): return self.ds.__exit__(*args)
        def read(self, *args, **kwargs):
            windows.append(kwargs['window'])
            return self.ds.read(*args, **kwargs)
    def open_once(*args, **kwargs):
        opened.append(args)
        return Counted(original(*args, **kwargs))
    monkeypatch.setattr(rasterio, 'open', open_once)
    summary, _ = adapter.read_points(points, '2026-10-26')
    assert len(summary['samples']) == 81 and len(opened) == 1 and len(windows) <= 81
    assert all(rows[1] - rows[0] == columns[1] - columns[0] == 1 for rows, columns in windows)


def test_rotated_native_metadata_is_unknown_without_advertised_resolution(tmp_path):
    from affine import Affine
    adapter, points, _, _ = fixture(tmp_path, transform=Affine(10000, 1, 1110000, 0, -10000, 8420000))
    summary, _ = adapter.read_points(points, '2026-10-26')
    assert summary['resolution_m'] is None and all(row['scl_class'] is None for row in summary['samples'])


def test_latest_unreadable_scene_does_not_fall_back_to_an_older_class(tmp_path):
    adapter, points, calls, payload = fixture(tmp_path)
    latest = deepcopy(payload['features'][0]); latest['id'] = 'latest'; latest['properties']['datetime'] = '2026-10-26T11:00:00Z'; latest['assets'] = {}
    payload['features'].append(latest)
    summary, _ = adapter.read_points(points, '2026-10-26')
    assert all(row['scl_class'] is None for row in summary['samples']) and len(calls) == 1
