"""V12 native cached HWSD reference-soil adapter."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from apps.api.hwsd_sources import HWSDSources
from apps.api.soil_type import SoilTypeSource


ROOT = Path(__file__).resolve().parents[2]
NATIVE_CACHE = ROOT / "runtime" / "data" / "hwsd-sources"
POINT = (59.98500020992624, 10.733331822658165)


def test_native_cached_point_returns_verified_wrb_reference_without_network(tmp_path: Path) -> None:
    adapter = HWSDSources(NATIVE_CACHE)
    soil, source = SoilTypeSource(tmp_path, adapter_lookup=lambda: adapter).read_point(*POINT)

    assert soil == {
        "status": "available",
        "basis": "hwsd_v2_smu_dominant_soil",
        "requested_point": {"latitude": POINT[0], "longitude": POINT[1]},
        "map_unit_id": 10124,
        "wrb_code": "PZal",
        "wrb_name": "Albic Podzols",
        "share_percent": 70.0,
        "resolution_arc_seconds": 30,
        "temporal_scope": "static_reference",
        "classification_system": "WRB 2022",
        "spatial_scope": "soil_mapping_unit",
    }
    assert source["id"] == "hwsd-v2"
    assert source["product"] == "Harmonized World Soil Database v2.0"
    assert source["status"] == source["qc"] == "available"
    assert source["observed_at"] is None
    assert source["data"]["commercial_reuse"] == "not_established"
    assert source["content_sha256"].startswith("sha256:")
    assert "http" not in json.dumps(source)


def test_missing_cached_archives_is_offline_unavailable(tmp_path: Path) -> None:
    adapter = HWSDSources(tmp_path / "missing")
    soil, source = SoilTypeSource(tmp_path / "evidence", adapter_lookup=lambda: adapter).read_point(*POINT)
    assert soil["status"] == "unavailable"
    assert soil["map_unit_id"] is None
    assert source["status"] == "unavailable"


def test_partial_map_unit_does_not_invent_wrb_class(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = HWSDSources(tmp_path / "raw")
    monkeypatch.setattr(adapter, "_sample_raster", lambda *_: (10124, {"crs": "OGC:CRS84", "width": 43200, "height": 21600, "row": 1, "column": 1, "resolution_arc_seconds": 30, "nodata": 0}))
    monkeypatch.setattr(adapter, "_attributes", lambda *_: ({"rows": [{"HWSD2_SMU_ID": "10124", "WRB4": "bad token", "SHARE": "70"}]}, {"status": "available"}))
    monkeypatch.setattr(SoilTypeSource, "_cached_archives", lambda *_: ("r", "d", "m"))
    soil, source = SoilTypeSource(tmp_path / "evidence", adapter_lookup=lambda: adapter).read_point(*POINT)
    assert soil["status"] == "partial"
    assert soil["map_unit_id"] == 10124
    assert soil["wrb_code"] is soil["wrb_name"] is soil["share_percent"] is None
    assert source["status"] == "partial"
    assert soil["resolution_arc_seconds"] == 30


def test_complete_result_is_cached_by_adapter_identity_and_is_deep_copied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = HWSDSources(tmp_path / "raw")
    calls = 0
    def sampled(*_):
        nonlocal calls
        calls += 1
        return 10124, {"crs": "OGC:CRS84", "width": 43200, "height": 21600, "row": 1, "column": 1, "resolution_arc_seconds": 30, "nodata": 0}
    monkeypatch.setattr(adapter, "_sample_raster", sampled)
    monkeypatch.setattr(adapter, "_attributes", lambda *_: ({"rows": [{"HWSD2_SMU_ID": "10124", "WRB4": "PZal", "SHARE": "70"}]}, {"status": "available"}))
    monkeypatch.setattr(SoilTypeSource, "_cached_archives", lambda *_: ("r", "d", "m"))
    monkeypatch.setattr(SoilTypeSource, "_wrb_name", lambda *_: "Albic Podzols")
    clock = iter((10.0, 11.0)).__next__
    source = SoilTypeSource(tmp_path / "evidence", adapter_lookup=lambda: adapter, monotonic_clock=clock)
    first, _ = source.read_point(*POINT)
    first["wrb_name"] = "mutated"
    second, _ = source.read_point(*POINT)
    assert calls == 1
    assert second["wrb_name"] == "Albic Podzols"


@pytest.mark.parametrize('code', [' PZal', 'PZal ', '\tPZal'])
def test_malformed_native_identifier_is_not_trimmed_into_a_successful_lookup(tmp_path, monkeypatch, code):
    adapter = HWSDSources(tmp_path / 'native')
    calls = []
    monkeypatch.setattr(SoilTypeSource, '_cached_archives', lambda *_: ('a' * 64, 'b' * 64, 'c' * 64))
    monkeypatch.setattr(adapter, '_sample_raster', lambda *_: (10124, {'crs': 'OGC:CRS84', 'width': 43200, 'height': 21600, 'row': 1, 'column': 1, 'resolution_arc_seconds': 30}))
    monkeypatch.setattr(adapter, '_attributes', lambda *_: ({'rows': [{'HWSD2_SMU_ID': '10124', 'WRB4': code, 'SHARE': '70'}]}, {'status': 'available'}))
    monkeypatch.setattr(adapter, '_mdb_tools', lambda: {'mdb-sql': Path('not-executed')})
    monkeypatch.setattr(adapter, '_run_mdb', lambda *_args, **kwargs: (calls.append(kwargs) or 'ID|VALUE|CODE\n145|Albic Podzols|PZal\n'))
    soil, _ = SoilTypeSource(tmp_path / 'evidence', adapter_lookup=lambda: adapter).read_point(*POINT)
    assert soil['status'] == 'partial' and soil['wrb_code'] is None and soil['wrb_name'] is None
    assert calls == [], 'Validate the original literal code before SQL, not a repaired token'
