from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from apps.api.sentinel1_sources import Sentinel1Sources


SELECTED = "2026-10-25"


def _item(identifier: str, observed: str, href: str = "https://sentinel1euwestrtc.blob.core.windows.net/sentinel1-grd-rtc/rtc.tiff") -> dict:
    return {
        "id": identifier,
        "collection": "sentinel-1-rtc",
        "properties": {
            "datetime": observed,
            "sar:instrument_mode": "IW",
            "sar:polarizations": ["VV", "VH"],
            "sat:orbit_state": "ascending",
            "sat:relative_orbit": 73,
            "sar:frequency_band": "C",
            "pc:processing_level": "RTC",
            "s1:processing_baseline": "3.71",
        },
        "assets": {"vv": {"href": href, "type": "image/tiff; application=geotiff"}, "vh": {"href": href, "type": "image/tiff; application=geotiff"}},
    }


def test_read_returns_actual_rtc_window_with_clear_units_and_no_signed_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url == httpx.URL(Sentinel1Sources.STAC_SEARCH_URL)
        body = json.loads(request.content)
        assert body["collections"] == ["sentinel-1-rtc"]
        assert body["datetime"] == "2026-10-15T00:00:00Z/2026-10-25T23:59:59Z"
        return httpx.Response(200, json={"features": [_item("future", "2026-10-26T00:00:00Z"), _item("older", "2026-10-22T05:12:01Z")]})

    def sampled(self: Sentinel1Sources, item: dict, latitude: float, longitude: float) -> tuple[dict, bytes]:
        assert item["id"] == "older"
        assert latitude == 59.91 and longitude == 10.75
        return ({
            "bands": {
                "vv": {"linear": 0.123, "db": -9.100948885, "unit": "gamma0_linear", "nodata": 0.0, "masked": False},
                "vh": {"linear": 0.021, "db": -16.777807052, "unit": "gamma0_linear", "nodata": 0.0, "masked": False},
            },
            "window": {"row": 120, "column": 220, "width": 3, "height": 3},
            "qc": {"status": "available", "missing_masks": ["layover_shadow", "water", "snow", "vegetation", "rain_at_acquisition"]},
        }, b"actual small raster evidence")

    monkeypatch.setattr(Sentinel1Sources, "_read_rtc_window", sampled)
    adapter = Sentinel1Sources(tmp_path, transport=httpx.MockTransport(handler))
    assert calls == []
    result = adapter.read(59.91, 10.75, SELECTED)

    assert len(calls) == 1
    assert set(result) == {"satellite", "source"}
    assert result["satellite"]["status"] == "available"
    assert result["satellite"]["scene_age_days"] == 3
    assert result["satellite"]["vv"]["linear"] == 0.123
    assert result["satellite"]["vv"]["unit"] == "gamma0_linear"
    assert result["satellite"]["vv"]["db"] == pytest.approx(-9.100948885)
    assert result["source"]["id"] == "sentinel-1-grd"
    assert result["source"]["product"] == "Sentinel-1 GRD-derived RTC"
    assert result['source']['qc'] == 'partial'
    assert result['satellite']['qc']['status'] == 'partial'
    assert result["source"]["data"]["processing"] == "external_provider_rtc"
    assert result["source"]["data"]["orbit_direction"] == "ascending"
    assert result["source"]["content_sha256"].startswith("sha256:")
    rendered = json.dumps(result)
    assert "token=" not in rendered and "sig=" not in rendered and "blob.core.windows.net" not in rendered
    assert list((tmp_path / "evidence").glob("*.json"))


def test_read_returns_partial_when_no_scene_exists_in_bounded_past_window(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"features": [_item("future", "2026-10-26T00:00:00Z")]})

    result = Sentinel1Sources(tmp_path, transport=httpx.MockTransport(handler)).read(59.91, 10.75, SELECTED)

    assert result["satellite"] == {"status": "partial", "item": None, "scene_age_days": None, "vv": None, "vh": None, "note": "У 10-денному ретроспективному вікні до обраної UTC-дати сцени немає; значення не вигадано."}
    assert result["source"]["status"] == result["source"]["qc"] == "partial"
    assert result["source"]["observed_at"] is None


def test_read_marks_nodata_window_partial_without_inventing_backscatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"features": [_item("valid", "2026-10-25T05:12:01Z")]})

    monkeypatch.setattr(Sentinel1Sources, "_read_rtc_window", lambda *_: ({"bands": {"vv": {"linear": None, "db": None, "unit": "gamma0_linear", "nodata": 0, "masked": True}, "vh": {"linear": None, "db": None, "unit": "gamma0_linear", "nodata": 0, "masked": True}}, "window": {"width": 1, "height": 1}, "qc": {"status": "unavailable", "missing_masks": ["layover_shadow"]}}, b"nodata"))
    result = Sentinel1Sources(tmp_path, transport=httpx.MockTransport(handler)).read(59.91, 10.75, SELECTED)

    assert result["satellite"]["status"] == "partial"
    assert result["satellite"]["vv"]["linear"] is None
    assert result["source"]["status"] == "partial"
    assert "NoData" in result["source"]["note"]



def test_asset_allowlist_accepts_the_current_provider_rtc_host_only(tmp_path: Path) -> None:
    adapter = Sentinel1Sources(tmp_path)
    assert adapter._public_asset("https://sentinel1euwestrtc.blob.core.windows.net/sentinel1-grd-rtc/x.tiff")
    assert not adapter._public_asset("https://example.invalid/x.tiff")
    assert not adapter._public_asset("https://sentinel1euwestrtc.blob.core.windows.net/x.tiff?sig=secret")


@pytest.mark.parametrize("signed", [
    "https://example.invalid/redirected.tiff?sig=opaque",
    "https://sentinel1euwestrtc.blob.core.windows.net/other/rtc.tiff?sig=opaque",
    "https://sentinel1euwestrtc.blob.core.windows.net/sentinel1-grd-rtc/different.tiff?sig=opaque",
    "https://user:password@sentinel1euwestrtc.blob.core.windows.net/sentinel1-grd-rtc/rtc.tiff?sig=opaque",
])
def test_signer_cannot_change_the_approved_asset_identity(tmp_path, signed):
    adapter = Sentinel1Sources(tmp_path, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"href": signed})))
    with pytest.raises(ValueError, match="approved"):
        adapter._sign(_item("fixture", "2026-10-25T00:00:00Z")["assets"]["vv"]["href"])


def test_signer_may_add_query_to_the_exact_approved_asset(tmp_path):
    href = _item("fixture", "2026-10-25T00:00:00Z")["assets"]["vv"]["href"]
    adapter = Sentinel1Sources(tmp_path, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"href": href + "?sig=opaque"})))
    assert adapter._sign(href) == href + "?sig=opaque"


def test_rejects_invalid_inputs_and_bounds_evidence_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        Sentinel1Sources(tmp_path).read(91, 10.75, SELECTED)
    with pytest.raises(ValueError):
        Sentinel1Sources(tmp_path).read(59.91, 10.75, "25-10-2026")

    adapter = Sentinel1Sources(tmp_path / "cache", cache_max_entries=1)
    monkeypatch.setattr(adapter, "_stac", lambda *_: [_item("one", "2026-10-25T05:12:01Z")])
    monkeypatch.setattr(adapter, "_read_rtc_window", lambda *_: ({"bands": {"vv": {"linear": 1.0, "db": 0.0, "unit": "gamma0_linear", "nodata": 0, "masked": False}, "vh": {"linear": 1.0, "db": 0.0, "unit": "gamma0_linear", "nodata": 0, "masked": False}}, "window": {"width": 1, "height": 1}, "qc": {"status": "available", "missing_masks": []}}, b"x"))
    adapter.read(59.91, 10.75, SELECTED)
    adapter.read(59.92, 10.75, SELECTED)
    assert len(list((tmp_path / "cache" / "evidence").glob("*.json"))) <= 1
