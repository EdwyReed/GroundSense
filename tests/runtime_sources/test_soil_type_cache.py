"""V12 cache concurrency and atomic evidence regressions (mocked native I/O)."""
from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
import json
from pathlib import Path
import threading
import weakref

import pytest

from apps.api.hwsd_sources import HWSDSources
from apps.api.soil_type import SoilTypeSource

POINT = (59.98500020992624, 10.733331822658165)


def native_fixture(tmp_path, monkeypatch):
    adapter = HWSDSources(tmp_path / 'native')
    monkeypatch.setattr(SoilTypeSource, '_cached_archives', lambda *_: ('a' * 64, 'b' * 64, 'c' * 64))
    monkeypatch.setattr(adapter, '_attributes', lambda *_: ({'rows': [{'HWSD2_SMU_ID': '10124', 'WRB4': 'PZal', 'SHARE': '70'}]}, {'status': 'available'}))
    monkeypatch.setattr(SoilTypeSource, '_wrb_name', lambda *_: 'Albic Podzols')
    metadata = {'crs': 'OGC:CRS84', 'width': 43200, 'height': 21600, 'row': 1, 'column': 1, 'resolution_arc_seconds': 30}
    return adapter, metadata


def test_simultaneous_cold_reads_single_flight_native_work(tmp_path, monkeypatch):
    adapter, metadata = native_fixture(tmp_path, monkeypatch)
    entered, release, second_started, duplicate = (threading.Event() for _ in range(4))
    count = 0
    def sample(*_):
        nonlocal count
        count += 1
        if count == 1:
            entered.set()
            assert release.wait(5)
        else:
            duplicate.set()
        return 10124, metadata
    monkeypatch.setattr(adapter, '_sample_raster', sample)
    source = SoilTypeSource(tmp_path / 'evidence', adapter_lookup=lambda: adapter)
    def second():
        second_started.set()
        return source.read_point(*POINT)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(source.read_point, *POINT)
        assert entered.wait(5)
        another = pool.submit(second)
        assert second_started.wait(5)
        try:
            assert not duplicate.wait(.2), 'Second context repeated cold native I/O'
        finally:
            release.set()
        a, b = first.result(timeout=5), another.result(timeout=5)
    assert count == 1 and a == b and a[0]['status'] == 'available'
    a[0]['requested_point']['latitude'] = 0
    assert b[0]['requested_point']['latitude'] == POINT[0]


def test_cache_retains_adapter_identity_instead_of_only_a_reusable_integer_id(tmp_path, monkeypatch):
    adapter = HWSDSources(tmp_path / 'native')
    current: list[HWSDSources | None] = [adapter]
    ref = weakref.ref(adapter)
    monkeypatch.setattr(SoilTypeSource, '_read', lambda self, adapter, lat, lon: (self._dto(lat, lon, status='available'), {'status': 'available'}))
    source = SoilTypeSource(tmp_path / 'evidence', adapter_lookup=lambda: current[0])
    source.read_point(*POINT)
    current[0] = None
    del adapter
    gc.collect()
    assert ref() is not None, 'Cached id(adapter) must not be recycled for an unrelated adapter'


def test_complete_cache_expiry_tiny_coordinate_changes_lru_and_adapter_change(tmp_path, monkeypatch):
    adapter, metadata = native_fixture(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(adapter, '_sample_raster', lambda *args: (calls.append(args) or (10124, metadata)))
    now = [10.0]
    current: list[HWSDSources | None] = [adapter]
    source = SoilTypeSource(tmp_path / 'evidence', adapter_lookup=lambda: current[0], monotonic_clock=lambda: now[0])
    monkeypatch.setattr(SoilTypeSource, 'MAX_CACHE_ENTRIES', 2)
    first = source.read_point(*POINT)
    assert source.read_point(*POINT) == first and len(calls) == 1
    now[0] += source.TTL_SECONDS + 1
    source.read_point(*POINT)
    assert len(calls) == 2
    source.read_point(POINT[0] + 1e-9, POINT[1])
    source.read_point(POINT[0] + 2e-9, POINT[1])
    assert len(calls) == 4
    source.read_point(*POINT)
    assert len(calls) == 5 and len(source._cache) == 2
    current[0] = None
    assert source.read_point(*POINT)[0]['status'] == 'unavailable'
    current[0] = adapter
    assert source.read_point(*POINT)[0]['status'] == 'available' and len(calls) == 5


def test_evidence_replacement_is_atomic_and_failed_replacement_leaves_prior_bytes(tmp_path, monkeypatch):
    source = SoilTypeSource(tmp_path, adapter_lookup=lambda: None)
    evidence = {'point': [10.73, 59.98], 'code': 'PZal'}
    digest = source._save_evidence(evidence)
    destination = tmp_path / 'soil-type-evidence' / (digest + '.json')
    before = destination.read_bytes()
    replaced = []
    def fail_replace(path, target):
        replaced.append(path)
        assert target == destination and path != destination
        assert path.read_bytes() == before
        raise OSError('simulated atomic replace failure')
    monkeypatch.setattr(Path, 'replace', fail_replace)
    with pytest.raises(OSError):
        source._save_evidence(evidence)
    assert replaced and destination.read_bytes() == before
    assert all(not path.exists() for path in replaced)
    assert hashlib.sha256(before).hexdigest() == digest
    assert json.loads(before) == evidence
