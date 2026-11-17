"""OSM adapter tests use explicit fixtures, not evidence of a live map read."""
import json
from datetime import UTC, datetime
from pathlib import Path
import httpx
import pytest
from apps.api.osm_sources import OSMSources


@pytest.fixture(autouse=True)
def fixed_source_clock(monkeypatch):
    # Current-vs-historical extraction is the behavior under test; do not let
    # a midnight rollover silently turn current-map fixtures into history.
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=UTC):
            return datetime(2026, 10, 25, 12, tzinfo=UTC).astimezone(tz)
    monkeypatch.setattr("apps.api.osm_sources.datetime", FixedDateTime)


def response(request):
    assert request.url == httpx.URL(OSMSources.ENDPOINT)
    assert "GroundSense" in request.headers["User-Agent"]
    assert "around:250" in request.content.decode()
    return httpx.Response(200, json={"osm3s": {"timestamp_osm_base": "2026-10-25T10:00:00Z"}, "elements": [{"type": "way", "id": 123, "version": 4, "timestamp": "2025-01-01T00:00:00Z", "tags": {"highway": "track", "surface": "gravel"}, "geometry": [{"lat":59.91,"lon":10.75},{"lat":59.9101,"lon":10.7501}]}]})


def test_real_parser_keeps_ids_tags_missing_fields_and_provenance(tmp_path):
    adapter = OSMSources(tmp_path, transport=httpx.MockTransport(response))
    result = adapter.read(59.91, 10.75, "2026-10-25")
    source, ways = result["source"], result["ways"]
    assert source["id"] == "openstreetmap" and source["status"] == "available"
    assert source["data"]["completeness"] == "unknown"
    assert ways[0]["osm_id"] == 123 and ways[0]["tags"]["surface"] == "gravel"
    assert ways[0]["tags"]["maxweight"] is None
    assert ways[0]["geometry"]["type"] == "LineString"
    digest = source["content_sha256"].removeprefix("sha256:")
    assert (tmp_path / "raw" / (digest + ".json")).is_file()
    assert "passable" not in json.dumps(result)


def test_cache_and_persisted_daily_budget_prevent_repeated_public_requests(tmp_path):
    calls = []
    def counted(request):
        calls.append(request)
        return response(request)
    adapter = OSMSources(tmp_path, transport=httpx.MockTransport(counted), daily_limit=1)
    first = adapter.read(59.91, 10.75, "2026-10-25")
    first["ways"].clear()
    assert len(adapter.read(59.91, 10.75, "2026-10-25")["ways"]) == 1
    assert len(calls) == 1
    restarted = OSMSources(tmp_path, transport=httpx.MockTransport(counted), daily_limit=1)
    assert restarted.read(59.92,10.75,"2026-10-25")["source"]["status"] == "unavailable"
    assert len(calls) == 1


def test_empty_or_failed_extract_does_not_prove_absence_of_roads(tmp_path):
    for status in [200, 503]:
        adapter = OSMSources(tmp_path / str(status), transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"elements": []})))
        result = adapter.read(59.91,10.75,"2026-10-25")
        assert result["source"]["status"] != "available"
        assert result["source"]["data"]["completeness"] == "unknown"
        assert result["ways"] == []


def test_small_current_osm_api_extract_is_used_when_overpass_is_unavailable(tmp_path):
    xml = b'<osm version="0.6"><node id="1" lat="59.91" lon="10.75"/><node id="2" lat="59.9101" lon="10.7501"/><way id="123" version="4"><nd ref="1"/><nd ref="2"/><tag k="highway" v="track"/><tag k="surface" v="gravel"/></way></osm>'
    calls = []
    def fallback(request):
        calls.append(request)
        if request.url.copy_with(query=None) == httpx.URL(OSMSources.ENDPOINT):
            return httpx.Response(502)
        assert request.url.copy_with(query=None) == httpx.URL(OSMSources.MAP_ENDPOINT)
        assert 'bbox' in request.url.params
        assert request.headers['Accept'] == 'application/xml'
        return httpx.Response(200, content=xml)
    result = OSMSources(tmp_path, transport=httpx.MockTransport(fallback)).read(59.91,10.75,"2026-10-25")
    assert result['source']['status'] == 'available'
    assert result['source']['data']['extraction'] == 'osm_api_bbox'
    assert result['ways'][0]['osm_id'] == 123
    assert len(calls) == 2
