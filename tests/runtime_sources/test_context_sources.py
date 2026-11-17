from __future__ import annotations

import json

import httpx
import pytest

from apps.api.context_sources import ContextSources


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.copy_with(query=None) == httpx.URL(ContextSources.CLC_IDENTIFY_URL):
        assert dict(request.url.params)["geometry"] == "10.75,59.91"
        return httpx.Response(200, json={"results": [{
            "layerId": 1,
            "layerName": "Corine Land Cover 2018 raster",
            "attributes": {"Raster.CODE_18": "123", "Raster.LABEL3": "Port areas", "Raster.Value": "5"},
        }]})
    if request.url.copy_with(query=None) == httpx.URL(ContextSources.TCD_IDENTIFY_URL):
        return httpx.Response(200, json={"value": "67", "properties": {"pixelType": "U8"}})
    if request.url == httpx.URL(ContextSources.HWSD_METADATA_URL):
        return httpx.Response(200, text="HWSD v2.0 GIS raster connected to soil attribute database; 30 arc-second")
    if request.url == httpx.URL(ContextSources.ESDAC_METADATA_URL):
        return httpx.Response(200, text='''<h1>Title in Russia. (Soil Map of Ukraine).</h1>
            <a href="/images/Eudasm/UA/russ_x76.jpg">Download</a>
            <span class="country">Ukraine</span><div>Voronina, A.V.; et al.</div><span>1977</span>''')
    raise AssertionError(f"unexpected {request.method} {request.url}")


def test_read_returns_real_point_values_only_when_identify_returns_them(tmp_path):
    adapter = ContextSources(tmp_path, transport=httpx.MockTransport(_handler))

    result = adapter.read(59.91, 10.75, "2026-10-25")

    assert set(result) == {"context", "sources"}
    assert result["context"]["corine_land_cover"] == {
        "class_code": 123, "class_label": "Port areas", "reference_year": 2018,
        "resolution_m": 100, "nodata": None,
        "note": "Статичний контекст земного покриву; не спостереження дороги.",
    }
    assert result["context"]["tree_cover_density"]["percent"] == 67
    assert result["context"]["tree_cover_density"]["reference_year"] == 2018
    assert result["context"]["hwsd_v2"]["map_unit_id"] is None
    assert result["context"]["esdac_ukraine_soil_map"]["point_soil_class"] is None
    records = {source["id"]: source for source in result["sources"]}
    assert records["corine-land-cover"]["status"] == "available"
    assert records["clms-tree-cover-density"]["status"] == "available"
    assert records["hwsd-v2"]["status"] == "partial"
    assert records["esdac-ukraine-soil-map"]["status"] == "partial"
    assert all(set(source) == set(ContextSources.SOURCE_KEYS) for source in result["sources"])
    assert all(source["content_sha256"].startswith("sha256:") for source in result["sources"])
    assert "token=" not in json.dumps(result).lower()
    assert "signed" not in json.dumps(result).lower()


def test_nodata_and_empty_identify_are_never_available_numeric_context(tmp_path):
    def no_data(request: httpx.Request) -> httpx.Response:
        if request.url.copy_with(query=None) == httpx.URL(ContextSources.CLC_IDENTIFY_URL):
            return httpx.Response(200, json={"results": []})
        if request.url.copy_with(query=None) == httpx.URL(ContextSources.TCD_IDENTIFY_URL):
            return httpx.Response(200, json={"value": "NoData", "properties": None})
        return _handler(request)

    result = ContextSources(tmp_path, transport=httpx.MockTransport(no_data)).read(59.91, 10.75, "2026-10-25")
    records = {source["id"]: source for source in result["sources"]}
    assert result["context"]["corine_land_cover"]["class_code"] is None
    assert result["context"]["tree_cover_density"]["percent"] is None
    assert records["corine-land-cover"]["status"] == "unavailable"
    assert records["clms-tree-cover-density"]["status"] == "unavailable"
    assert "поза покриттям" in records["corine-land-cover"]["note"]
    assert "NoData" in records["clms-tree-cover-density"]["note"]


def test_constructor_has_no_network_and_reuses_bounded_raw_evidence(tmp_path):
    calls: list[httpx.Request] = []

    def counted(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _handler(request)

    adapter = ContextSources(tmp_path, transport=httpx.MockTransport(counted), cache_max_entries=1)
    assert calls == []
    first = adapter.read(59.91, 10.75, "2026-10-25")
    count = len(calls)
    first["context"]["tree_cover_density"]["percent"] = 0
    second = adapter.read(59.91, 10.75, "2026-10-25")
    assert len(calls) == count
    assert second["context"]["tree_cover_density"]["percent"] == 67
    assert len(list((tmp_path / "raw").glob("*.bin"))) <= 4


@pytest.mark.parametrize("latitude,longitude,selected", [(91, 10.75, "2026-10-25"), (59.91, 10.75, "25-10-2026")])
def test_read_rejects_invalid_coordinates_and_date(tmp_path, latitude, longitude, selected):
    with pytest.raises(ValueError):
        ContextSources(tmp_path).read(latitude, longitude, selected)


def test_tcd_identify_carries_the_point_crs_in_esri_geometry(tmp_path):
    def handler(request):
        if request.url.copy_with(query=None) == httpx.URL(ContextSources.TCD_IDENTIFY_URL):
            assert request.url.params['geometry'].startswith('{'), 'ImageServer needs ESRI geometry, not ignored top-level sr'
            assert json.loads(request.url.params['geometry']) == {'x':10.75,'y':59.91,'spatialReference':{'wkid':4326}}
            return httpx.Response(200, json={'value':'58'})
        return _handler(request)
    result = ContextSources(tmp_path, transport=httpx.MockTransport(handler)).read(59.91,10.75,'2026-10-25')
    assert result['context']['tree_cover_density']['percent'] == 58
