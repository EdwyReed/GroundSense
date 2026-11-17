"""Selective canopy density must not run the full historical-context stack."""
import json
import httpx
import pytest


@pytest.mark.parametrize("value,expected", [("58", 58), ("0", 0), ("NoData", None), ("255", None)])
def test_selective_tcd_preserves_native_percent_nodata_year_and_crs(tmp_path, value, expected):
    from apps.api.tree_cover_density import TreeCoverDensity
    calls = []
    def provider(request):
        calls.append(request)
        assert request.url.copy_with(query=None) == httpx.URL(TreeCoverDensity.TCD_IDENTIFY_URL)
        assert json.loads(request.url.params["geometry"])["spatialReference"] == {"wkid": 4326}
        return httpx.Response(200, json={"value": value})
    adapter = TreeCoverDensity(tmp_path, transport=httpx.MockTransport(provider))
    assert calls == []
    result, source = adapter.read_point(59.985, 10.733)
    assert result["percent"] == expected
    assert result["reference_year"] == 2018
    assert source["id"] == "clms-tree-cover-density"
    assert source["content_sha256"].startswith("sha256:")
    assert len(calls) == 1


def test_selective_tcd_rejects_oversized_provider_json(tmp_path):
    from apps.api.tree_cover_density import TreeCoverDensity
    adapter = TreeCoverDensity(tmp_path, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"value": "58", "padding": "x" * 65536})))
    result, source = adapter.read_point(59.985, 10.733)
    assert result["percent"] is None
    assert source["status"] == "unavailable"
