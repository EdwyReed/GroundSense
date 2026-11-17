from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from apps.api.clms_sources import CLMSSources

pytestmark = pytest.mark.filterwarnings("ignore:Use `@` matmul.*:PendingDeprecationWarning")


def _tiff(value: int, *, nodata: int = 255, tags: dict[str, str] | None = None) -> bytes:
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", height=2, width=2, count=1, dtype="uint8", crs="EPSG:4326", transform=from_origin(10.0, 60.0, 1.0, 1.0), nodata=nodata) as dataset:
            dataset.write(np.full((1, 2, 2), value, dtype=np.uint8))
            dataset.update_tags(**(tags or {}))
        return memory.read()


def _product_zip(variable: str, value: int, quality: int) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(f"c_gls_{variable}_202610250000_CEURO_TEST.tif", _tiff(value, tags={"units": "%", "scale_factor": "1", "product_version": "v-test"}))
        bundle.writestr("c_gls_QFLAG_202610250000_CEURO_TEST.tif", _tiff(quality, nodata=255))
    return archive.getvalue()


def test_read_downloads_selected_clms_products_with_injected_token_and_returns_numeric_values(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.copy_with(query=None) == httpx.URL(CLMSSources.CATALOGUE_URL):
            dataset = "swi_europe_1km_daily_v2" if "swi_europe_1km_daily_v2" in str(request.url) else "ssm_europe_1km_daily_v1"
            product_id = "swi-id" if dataset.startswith("swi") else "ssm-id"
            product_name = "c_gls_SWI1km_202610251200_CEURO_SCATSAR_V2.1.1_cog" if dataset.startswith("swi") else "c_gls_SSM1km_202610250000_CEURO_S1CSAR_V1.2.1_cog"
            return httpx.Response(200, json={"value": [{"Id": product_id, "Name": product_name, "ContentDate": {"Start": "2026-10-25T00:00:00.000Z", "End": "2026-10-25T23:59:59.999Z"}, "Attributes": [{"Name": "productVersion", "Value": "v2.1.1" if dataset.startswith("swi") else "v1.2.1"}, {"Name": "fileFormat", "Value": "cog"}]}]})
        if request.url == httpx.URL(CLMSSources.download_url("swi-id")):
            assert request.headers["authorization"] == "Bearer token-value"
            return httpx.Response(200, content=_product_zip("SWI010", 44, 3))
        if request.url == httpx.URL(CLMSSources.download_url("ssm-id")):
            assert request.headers["authorization"] == "Bearer token-value"
            return httpx.Response(200, content=_product_zip("SSM", 27, 1))
        raise AssertionError(f"unexpected request {request.url}")

    result = CLMSSources(tmp_path, token_provider=lambda: "token-value", transport=httpx.MockTransport(handler)).read(59.91, 10.75, "2026-10-25")

    assert result["soil_moisture"]["swi"]["value"] == 44.0
    assert result["soil_moisture"]["swi"]["depth_index"] == "SWI010"
    assert result["soil_moisture"]["ssm"]["value"] == 27.0
    records = {source["id"]: source for source in result["sources"]}
    assert records["clms-swi-1km-v2"]["status"] == "available"
    assert records["clms-ssm-1km"]["data"]["point"]["qc"]["raw_value"] == 1
    assert all(record["observed_at"].startswith("2026-10-25") for record in records.values())
    assert "token-value" not in json.dumps(result)
    assert len(calls) == 4


def test_swi_uses_selected_nominal_utc_date_when_its_composite_starts_the_day_before(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.copy_with(query=None) == httpx.URL(CLMSSources.CATALOGUE_URL):
            assert "ContentDate/End ge 2026-10-23T00:00:00.000Z" in dict(request.url.params)["$filter"]
            if "swi_europe_1km_daily_v2" in dict(request.url.params)["$filter"]:
                return httpx.Response(200, json={"value": [{"Id": "swi-id", "ContentDate": {"Start": "2026-10-22T12:00:01.000Z", "End": "2026-10-23T12:00:00.000Z"}, "Attributes": [{"Name": "fileFormat", "Value": "cog"}, {"Name": "nominalDate", "Value": "2026-10-23T12:00:00.000Z"}]}]})
            return httpx.Response(200, json={"value": []})
        if request.url == httpx.URL(CLMSSources.download_url("swi-id")):
            return httpx.Response(200, content=_product_zip("SWI010", 55, 1))
        raise AssertionError(request.url)

    result = CLMSSources(tmp_path, token_provider=lambda: "injected", transport=httpx.MockTransport(handler)).read(59.91, 10.75, "2026-10-23")

    assert result["soil_moisture"]["swi"]["value"] == 55.0
    assert result["sources"][0]["observed_at"] == "2026-10-23T12:00:00Z"


def test_projected_raster_samples_the_transformed_wgs84_point():
    from rasterio.warp import transform
    xs,ys = transform('EPSG:4326','EPSG:3857',[10.75],[59.91])
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',height=2,width=2,count=1,dtype='uint8',crs='EPSG:3857',transform=from_origin(xs[0]-500,ys[0]+500,1000,1000),nodata=255) as dataset:
            dataset.write(np.full((1,2,2),42,dtype='uint8'))
        sampled = CLMSSources._sample_tiff(MemoryFile(memory.read()),59.91,10.75)
    assert sampled is not None and sampled[0] == 42


def test_missing_raster_units_are_not_invented_as_percent(tmp_path):
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as bundle:
        bundle.writestr('c_gls_SWI010_20261025.tif',_tiff(42))
    point=CLMSSources(tmp_path)._sample_zip(archive.getvalue(),'SWI',59.91,10.75,'swi')
    assert point is not None
    assert point['unit'] is None
    assert point['unit_known'] is False
    assert point['qc']['status'] != 'available'


def test_request_stops_stream_at_byte_limit_without_buffering_the_rest(tmp_path):
    consumed = []

    class ProductStream(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in (b"123", b"456", b"never-read"):
                consumed.append(chunk)
                yield chunk

    adapter = CLMSSources(tmp_path, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=ProductStream())))
    with pytest.raises(ValueError, match="size"):
        adapter._request("GET", adapter.download_url("fixture"), maximum_bytes=4)
    assert consumed == [b"123", b"456"]


@pytest.mark.parametrize("limit", ["_MAX_ZIP_MEMBERS", "_MAX_MEMBER_BYTES", "_MAX_UNCOMPRESSED_BYTES", "_MAX_COMPRESSION_RATIO"])
def test_zip_limits_are_checked_before_sampling_members(tmp_path, monkeypatch, limit):
    tiff = _tiff(42, tags={"units": "%"})
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("c_gls_SWI010_20261025.tif", tiff)
        archive.writestr("c_gls_QFLAG_20261025.tif", tiff)
    adapter = CLMSSources(tmp_path)
    maximum = {"_MAX_ZIP_MEMBERS": 1, "_MAX_MEMBER_BYTES": len(tiff) - 1,
               "_MAX_UNCOMPRESSED_BYTES": len(tiff) * 2 - 1, "_MAX_COMPRESSION_RATIO": 1.01}[limit]
    monkeypatch.setattr(adapter, limit, maximum, raising=False)
    with pytest.raises(ValueError, match="ZIP"):
        adapter._sample_zip(raw.getvalue(), "SWI", 59.91, 10.75, "swi")
