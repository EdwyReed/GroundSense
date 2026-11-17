from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import httpx
import numpy as np
import pytest
from rasterio.transform import from_origin

from apps.api.hwsd_sources import HWSDSources


def _raster_zip(value: int = 101) -> bytes:
    """A tiny BIL/HDR archive that GDAL can open through /vsizip/."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("nested/HWSD2.bil", np.full((2, 2), value, dtype="<u2").tobytes())
        bundle.writestr("nested/HWSD2.hdr", "\n".join((
            "BYTEORDER      I", "LAYOUT         BIL", "NROWS          2", "NCOLS          2", "NBANDS         1",
            "NBITS          16", "PIXELTYPE      UNSIGNEDINT", "NODATA         65535",
            "ULXMAP         10.25", "ULYMAP         59.75", "XDIM           0.5", "YDIM           0.5", "EPSG           4326",
        )))
        bundle.writestr("nested/HWSD2.prj", "GEOGCS[\"WGS 84\",DATUM[\"WGS_1984\",SPHEROID[\"WGS 84\",6378137,298.257223563]],PRIMEM[\"Greenwich\",0],UNIT[\"degree\",0.0174532925199433]]")
    return archive.getvalue()


def _db_zip() -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("HWSD2.mdb", b"not-an-access-db")
    return archive.getvalue()


def test_read_downloads_official_archives_once_and_samples_native_bil_via_vsizip(tmp_path: Path) -> None:
    raster = _raster_zip()
    database = _db_zip()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url == httpx.URL(HWSDSources.RASTER_ZIP_URL):
            return httpx.Response(200, content=raster)
        if request.url == httpx.URL(HWSDSources.DB_ZIP_URL):
            return httpx.Response(200, content=database)
        raise AssertionError(request.url)

    adapter = HWSDSources(tmp_path, transport=httpx.MockTransport(handler))
    assert calls == []
    result = adapter.read(59.91, 10.75, "2026-10-25")

    point = result["context"]["hwsd_v2"]
    source = result["sources"][0]
    assert point["map_unit_id"] == 101
    assert point["raster"]["dtype"] == "uint16"
    assert point["raster"]["crs"] in {"EPSG:4326", "OGC:CRS84"}
    assert point["raster"]["nodata"] == 65535.0
    assert point["attributes"] is None
    assert source["id"] == "hwsd-v2"
    assert source["status"] == "partial"
    assert source["content_sha256"] == "sha256:" + hashlib.sha256(raster).hexdigest()
    assert source["data"]["database"]["status"] == "unavailable"
    assert len(calls) == 2
    assert "природ" in source["note"].lower()
    assert "дорог" in source["note"].lower()
    assert "комерцій" in source["note"].lower()
    assert source['observed_at'] is None
    assert "https://" not in json.dumps(result)

    again = adapter.read(59.91, 10.75, "2026-10-25")
    assert again["context"]["hwsd_v2"]["map_unit_id"] == 101
    assert len(calls) == 2


def test_attributes_reads_only_matching_map_unit_with_native_mdb_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _db_zip()
    tools = tmp_path / "tools"
    tools.mkdir()
    script = tools / "mdb-tool"
    script.write_text("""#!/usr/bin/env python3
import sys
name = sys.argv[0]
if name.endswith('mdb-tables'):
    print('HWSD2_SMU')
elif name.endswith('mdb-schema'):
    print('CREATE TABLE HWSD2_SMU ("HWSD2_SMU_ID" INTEGER, "WRB4" VARCHAR, "OTHER" VARCHAR);')
elif name.endswith('mdb-sql'):
    query = sys.stdin.read()
    assert 'WHERE [HWSD2_SMU_ID] = 101' in query, query
    print('HWSD2_SMU_ID|WRB4|OTHER')
    print('101|Phaeozems|raw value')
else:
    raise SystemExit(2)
""", encoding="utf-8")
    script.chmod(0o755)
    for name in ("mdb-tables", "mdb-schema", "mdb-sql"):
        (tools / name).symlink_to(script.name)
    monkeypatch.setenv("PATH", f"{tools}:{os.environ['PATH']}")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=database)

    adapter = HWSDSources(tmp_path, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(adapter, "_mdb_tools", lambda: {name: tools / name for name in ("mdb-tables", "mdb-schema", "mdb-sql")})
    state = adapter._database_state()
    attributes, parser_state = adapter._attributes(101, state)

    assert attributes == {"rows": [{"HWSD2_SMU_ID": "101", "WRB4": "Phaeozems", "OTHER": "raw value"}]}
    assert parser_state["status"] == "available"
    assert parser_state["table"] == "HWSD2_SMU"
    assert parser_state["map_unit_column"] == "HWSD2_SMU_ID"
    assert (tmp_path / "raw" / "HWSD2.mdb").stat().st_size == len(b"not-an-access-db")


def test_attributes_returns_none_when_native_parser_rejects_mdb(tmp_path: Path) -> None:
    adapter = HWSDSources(tmp_path)
    state = {"status": "cached", "content_sha256": "sha256:test", "members": []}
    attributes, parser_state = adapter._attributes(101, state)
    assert attributes is None
    assert parser_state["status"] == "unavailable"


def test_read_returns_unavailable_without_synthetic_map_unit_when_raster_is_nodata(tmp_path: Path) -> None:
    raster = _raster_zip(65535)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raster if request.url == httpx.URL(HWSDSources.RASTER_ZIP_URL) else _db_zip())

    result = HWSDSources(tmp_path, transport=httpx.MockTransport(handler)).read(59.91, 10.75, "2026-10-25")
    assert result["context"]["hwsd_v2"]["map_unit_id"] is None
    assert result["sources"][0]["status"] == "unavailable"


@pytest.mark.parametrize("latitude, longitude, assessment_date", [(91, 10.75, "2026-10-25"), (59.91, 10.75, "25-10-2026")])
def test_read_rejects_invalid_request_values(tmp_path: Path, latitude: float, longitude: float, assessment_date: str) -> None:
    with pytest.raises(ValueError):
        HWSDSources(tmp_path).read(latitude, longitude, assessment_date)


def test_concurrent_first_reads_download_each_archive_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    gate=threading.Barrier(2)
    calls=[]
    def handler(request):
        calls.append(request)
        time.sleep(.05)
        return httpx.Response(200,content=_raster_zip())
    adapter=HWSDSources(tmp_path,transport=httpx.MockTransport(handler))
    def read(_):
        gate.wait(timeout=2)
        return adapter._archive('HWSD2_RASTER.zip',adapter.RASTER_ZIP_URL,adapter._MAX_RASTER_BYTES)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(read,range(2)))
    assert len(calls) == 1
    assert results[0] == results[1]


def test_sample_raster_exposes_native_pixel_metadata_without_changing_legacy_fields(tmp_path: Path) -> None:
    raster = _raster_zip(101)
    path = tmp_path / "HWSD2_RASTER.zip"
    path.write_bytes(raster)

    value, metadata = HWSDSources(tmp_path)._sample_raster(path, 59.91, 10.75)

    assert value == 101
    assert metadata["width"] == metadata["height"] == 2
    assert metadata["row"] == 0
    assert metadata["column"] == 1
    assert metadata["pixel_width_degrees"] == 0.5
    assert metadata["pixel_height_degrees"] == 0.5
    assert metadata["resolution_arc_seconds"] is None


@pytest.mark.parametrize('a,b,d,e', [(1/120, 0, 0, 1/120), (-1/120, 0, 0, -1/120), (1/120, 1/240, 0, -1/120)])
def test_non_north_up_global_grid_does_not_claim_native_resolution(tmp_path, monkeypatch, a, b, d, e):
    from affine import Affine
    import rasterio

    class Dataset:
        width, height = 43200, 21600
        transform = Affine(a, b, -180 if a > 0 else 180, d, e, -90 if e > 0 else 90)
        crs = rasterio.crs.CRS.from_epsg(4326)
        dtypes, nodata, driver = ['uint16'], 0, 'EHdr'
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, *_args, **_kwargs): return np.array([[10124]], dtype='uint16')

    archive = tmp_path / 'raster.zip'
    archive.write_bytes(_raster_zip())
    monkeypatch.setattr(rasterio, 'open', lambda *_: Dataset())
    sampled = HWSDSources(tmp_path)._sample_raster(archive, 0, 0)
    assert sampled is not None
    assert sampled[1]['resolution_arc_seconds'] is None
