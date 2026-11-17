"""Bounded numerical reads from Microsoft Planetary Computer Sentinel-1 RTC COGs.

This adapter reads the provider's already processed GRD-derived RTC product.  It
never represents the provider's RTC/calibration as local SAR processing and it
never treats raw digital numbers as calibrated backscatter.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx


class Sentinel1Sources:
    """Read one small VV/VH gamma0 window from the public Sentinel-1 RTC mirror."""

    STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
    SAS_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
    COLLECTION = "sentinel-1-rtc"
    PRODUCT = "Sentinel-1 GRD-derived RTC"
    PROVIDER = "Microsoft Planetary Computer"
    ASSET_HOSTS = {"sentinel1euwestrtc.blob.core.windows.net"}
    SOURCE_KEYS = ("id", "name", "product", "version", "status", "qc", "note", "retrieved_at", "observed_at", "content_sha256", "data")
    MISSING_MASKS = ("layover_shadow", "water", "snow", "vegetation", "rain_at_acquisition")

    def __init__(self, cache_dir: Path, *, transport: httpx.BaseTransport | None = None, timeout_seconds: float = 15.0, cache_max_entries: int = 32) -> None:
        if timeout_seconds <= 0 or cache_max_entries < 1:
            raise ValueError("timeout_seconds must be positive and cache_max_entries at least one")
        self.cache_dir = Path(cache_dir)
        self.evidence_dir = self.cache_dir / "evidence"
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.cache_max_entries = cache_max_entries
        self._read_cached = lru_cache(maxsize=cache_max_entries)(self._read)

    def read(self, latitude: float, longitude: float, assessment_date: str) -> dict[str, Any]:
        """Return only a scene at or before the selected UTC day, max ten days old."""
        lat = self._coordinate(latitude, "latitude", -90, 90)
        lon = self._coordinate(longitude, "longitude", -180, 180)
        selected = self._date(assessment_date)
        return deepcopy(self._read_cached(lat, lon, selected, int(time.monotonic() // 300)))

    def _read(self, latitude: float, longitude: float, selected: date, _cache_window: int) -> dict[str, Any]:
        retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        try:
            features = self._stac(latitude, longitude, selected)
            item = self._nearest_earlier(features, selected)
            if item is None:
                note = "У 10-денному ретроспективному вікні до обраної UTC-дати сцени немає; значення не вигадано."
                return self._empty("partial", note, retrieved_at, "partial", {"discovery": "stac_query", "asset_read": "none", "window_days": 10})
            descriptor = self._descriptor(item)
            age = self._age_days(descriptor["observed_at"], selected)
            if age is None or not 0 <= age <= 10:
                raise ValueError("selected scene violates retrospective window")
            sampled, raster_evidence = self._read_rtc_window(item, latitude, longitude)
            evidence = {
                "provider": self.PROVIDER,
                "collection": self.COLLECTION,
                "item": descriptor,
                "sample": sampled,
                "raster_evidence_sha256": hashlib.sha256(raster_evidence).hexdigest(),
            }
            digest = self._store_evidence(evidence)
            vv, vh = sampled["bands"]["vv"], sampled["bands"]["vh"]
            usable = any(band["linear"] is not None for band in (vv, vh))
            qc = sampled["qc"]["status"] if usable else "partial"
            if sampled['qc'].get('missing_masks') and qc == 'available':
                qc = 'partial'
                sampled['qc']['status'] = qc
            status = "available" if usable else "partial"
            note = (
                "Отримано числове вікно VV/VH з готового RTC COG; gamma0 у лінійних одиницях, dB обчислено як 10·log10(gamma0). "
                "RTC, калібрування, terrain correction і орторектифікацію виконав зовнішній постачальник; локальної SAR-обробки не заявлено. Доступність чисел не означає повного QC: додаткові маски не отримано."
                if usable else
                "RTC COG прочитано, але центральний піксель має NoData; зворотне розсіяння не підставлено."
            )
            satellite = {
                "status": status, "item": descriptor, "scene_age_days": age,
                "vv": vv, "vh": vh, "window": sampled["window"], "qc": sampled["qc"],
                "note": "Сигнал є проксі поверхні, не вимірюванням прохідності, несучої здатності або стану дороги.",
            }
            source = self._source(status, qc, note, retrieved_at, descriptor["observed_at"], digest, {
                "discovery": "planetary_computer_stac", "extraction": "rasterio_cog_window",
                "processing": "external_provider_rtc", "calibration": "provider RTC gamma0; not local calibration",
                "units": {"linear": "gamma0_linear", "db": "dB", "db_formula": "10*log10(linear), only for linear > 0"},
                "item": descriptor, "scene_age_days": age, "orbit_direction": descriptor["orbit_direction"],
                "incidence_angle_degrees": descriptor["incidence_angle_degrees"], "qc": sampled["qc"],
            })
            return {"satellite": satellite, "source": source}
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            note = f"Неможливо отримати числове RTC-значення: {type(exc).__name__}. Дані не синтезовано."
            return self._empty("unavailable", note, retrieved_at, "unavailable", {"discovery": "failed", "asset_read": "none"})

    def _empty(self, status: str, note: str, retrieved_at: str, qc: str, data: dict[str, Any]) -> dict[str, Any]:
        satellite = {"status": status, "item": None, "scene_age_days": None, "vv": None, "vh": None, "note": note}
        return {"satellite": satellite, "source": self._source(status, qc, note, retrieved_at, None, None, data)}

    def _stac(self, latitude: float, longitude: float, selected: date) -> list[dict[str, Any]]:
        body = {
            "collections": [self.COLLECTION],
            "bbox": [round(longitude - 0.003, 6), round(latitude - 0.003, 6), round(longitude + 0.003, 6), round(latitude + 0.003, 6)],
            "datetime": f"{(selected - timedelta(days=10)).isoformat()}T00:00:00Z/{selected.isoformat()}T23:59:59Z",
            "limit": 100,
        }
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = client.post(self.STAC_SEARCH_URL, json=body, headers={"Accept": "application/geo+json"})
        response.raise_for_status()
        payload = response.json()
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise ValueError("STAC features missing")
        return [item for item in features if isinstance(item, dict)]

    def _read_rtc_window(self, item: dict[str, Any], latitude: float, longitude: float) -> tuple[dict[str, Any], bytes]:
        import rasterio
        from rasterio.windows import Window
        from rasterio.warp import transform

        assets = item.get("assets")
        if not isinstance(assets, dict):
            raise ValueError("RTC assets missing")
        bands: dict[str, Any] = {}
        window_data: dict[str, int] | None = None
        for polarization in ("vv", "vh"):
            asset = assets.get(polarization)
            href = asset.get("href") if isinstance(asset, dict) else None
            if not isinstance(href, str) or not self._public_asset(href):
                raise ValueError(f"approved RTC {polarization} asset unavailable")
            signed = self._sign(href)
            metadata = asset.get("raster:bands") if isinstance(asset.get("raster:bands"), list) else []
            metadata = metadata[0] if metadata and isinstance(metadata[0], dict) else {}
            env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff", "CPL_VSIL_CURL_CACHE_SIZE": str(2 * 1024 * 1024), "GDAL_HTTP_MAX_RETRY": "0", "GDAL_HTTP_TIMEOUT": str(int(self.timeout_seconds))}
            with rasterio.Env(**env), rasterio.open(signed) as dataset:
                if dataset.crs is None:
                    raise ValueError("RTC raster CRS missing")
                xs, ys = transform("EPSG:4326", dataset.crs, [longitude], [latitude])
                row, col = dataset.index(xs[0], ys[0])
                if not (0 <= row < dataset.height and 0 <= col < dataset.width):
                    raise ValueError("point outside RTC extent")
                left, top = max(0, col - 1), max(0, row - 1)
                window = Window(left, top, min(3, dataset.width - left), min(3, dataset.height - top))
                values = dataset.read(1, window=window, masked=True)
                center = values[row - top, col - left]
                masked = bool(getattr(center, "mask", False))
                raw = None if masked else float(center)
                scale = self._number_or(metadata.get("scale"), dataset.scales[0] if dataset.scales else 1.0)
                offset = self._number_or(metadata.get("offset"), dataset.offsets[0] if dataset.offsets else 0.0)
                linear = None if raw is None else raw * scale + offset
                # A non-positive backscatter coefficient cannot be converted to dB.
                db = 10 * math.log10(linear) if linear is not None and linear > 0 else None
                bands[polarization] = {"linear": linear, "db": db, "unit": "gamma0_linear", "raw_value": raw, "scale": scale, "offset": offset, "nodata": metadata.get("nodata", dataset.nodata), "masked": masked}
                window_data = {"row": int(top), "column": int(left), "width": int(window.width), "height": int(window.height)}
        missing = list(self.MISSING_MASKS)
        status = "available" if not missing and all(bands[name]["linear"] is not None for name in bands) else "partial"
        result = {"bands": bands, "window": window_data, "qc": {"status": status, "missing_masks": missing, "basis": "NoData mask from RTC COG only; no layover/shadow/water/snow/vegetation/rain masks supplied by this read"}}
        return result, json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def _sign(self, href: str) -> str:
        """Use only the provider's fixed signer; signed URLs never enter DTO/evidence."""
        if not self._public_asset(href):
            raise ValueError("approved RTC asset required")
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = client.get(self.SAS_SIGN_URL, params={"href": href}, headers={"Accept": "application/json"})
        response.raise_for_status()
        signed = response.json().get("href")
        if not isinstance(signed, str) or httpx.URL(signed).copy_with(query=None) != httpx.URL(href):
            raise ValueError("signer changed the approved RTC asset")
        return signed

    def _descriptor(self, item: dict[str, Any]) -> dict[str, Any]:
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        observed = properties.get("datetime") or properties.get("start_datetime")
        if not isinstance(observed, str):
            raise ValueError("scene datetime missing")
        return {
            "id": item.get("id"), "collection": item.get("collection"), "observed_at": observed,
            "instrument_mode": properties.get("sar:instrument_mode"), "polarizations": properties.get("sar:polarizations"),
            "orbit_direction": properties.get("sat:orbit_state") or properties.get("s1:orbit_direction"),
            "relative_orbit": properties.get("sat:relative_orbit") or properties.get("sat:relative_orbit_number"),
            "incidence_angle_degrees": properties.get("sar:incidence_angle"),
            "processing_level": properties.get("pc:processing_level") or "RTC",
            "processing_baseline": properties.get("s1:processing_baseline"),
        }

    @staticmethod
    def _nearest_earlier(features: list[dict[str, Any]], selected: date) -> dict[str, Any] | None:
        cutoff = datetime.combine(selected + timedelta(days=1), datetime.min.time(), UTC)
        candidates: list[tuple[datetime, dict[str, Any]]] = []
        for item in features:
            stamp = (item.get("properties") or {}).get("datetime")
            if isinstance(stamp, str):
                try:
                    observed = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)
                    if observed < cutoff:
                        candidates.append((observed, item))
                except ValueError:
                    pass
        return max(candidates, default=(None, None), key=lambda pair: pair[0])[1]

    def _store_evidence(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        target = self.evidence_dir / f"{digest}.json"
        if not target.exists():
            temporary = target.with_name(f".{target.name}.{time.time_ns()}.tmp")
            try:
                temporary.write_bytes(raw)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        entries = sorted(self.evidence_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in entries[self.cache_max_entries:]:
            path.unlink(missing_ok=True)
        return f"sha256:{digest}"

    def _source(self, status: str, qc: str, note: str, retrieved_at: str, observed_at: str | None, digest: str | None, data: dict[str, Any]) -> dict[str, Any]:
        result = {"id": "sentinel-1-grd", "name": "Sentinel-1", "product": self.PRODUCT, "version": "Planetary Computer sentinel-1-rtc", "status": status, "qc": qc, "note": note, "retrieved_at": retrieved_at, "observed_at": observed_at, "content_sha256": digest, "data": data}
        assert tuple(result) == self.SOURCE_KEYS
        return result

    @classmethod
    def _public_asset(cls, href: str) -> bool:
        parsed = httpx.URL(href)
        return (parsed.scheme == "https" and parsed.host in cls.ASSET_HOSTS
                and parsed.port in (None, 443) and not parsed.userinfo and not parsed.query and not parsed.fragment
                and parsed.path.startswith("/sentinel1-grd-rtc/") and parsed.path.lower().endswith((".tif", ".tiff")))

    @staticmethod
    def _number_or(value: Any, default: Any) -> float:
        try:
            candidate = float(default if value is None else value)
            return candidate if math.isfinite(candidate) else 1.0
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _age_days(observed_at: str, selected: date) -> int | None:
        try:
            return (selected - datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone(UTC).date()).days
        except ValueError:
            return None

    @staticmethod
    def _coordinate(value: Any, name: str, low: float, high: float) -> float:
        if type(value) not in (int, float) or not math.isfinite(float(value)) or not low <= float(value) <= high:
            raise ValueError(f"{name} must be a finite WGS84 coordinate")
        return float(value)

    @staticmethod
    def _date(value: Any) -> date:
        if not isinstance(value, str):
            raise ValueError("assessment_date must be YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("assessment_date must be YYYY-MM-DD") from exc
