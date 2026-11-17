"""Bounded Sentinel-2 Scene Classification point observations."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, date, datetime, time as daytime, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx

from apps.api.remote_sources import RemoteSources


class SurfaceObservation:
    """Read exactly one native SCL cell for one selected off-road route point."""

    STAC_URL = RemoteSources.STAC_URL
    COLLECTION = "sentinel-2-l2a"
    CACHE_TTL_SECONDS = 300.0
    CACHE_MAX_ENTRIES = 64
    MAX_RESPONSE_BYTES = 1024 * 1024
    _SCL = {2: ("partial", "shadow"), 3: ("partial", "shadow"), 4: ("available", "vegetation"), 5: ("available", "not_vegetated"), 6: ("available", "water"), 8: ("partial", "cloud"), 9: ("partial", "cloud"), 10: ("partial", "cloud"), 11: ("partial", "snow_ice")}

    def __init__(self, cache_dir: Path, *, transport: httpx.BaseTransport | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cache: OrderedDict[tuple[float, float, str], tuple[float, tuple[dict[str, Any], dict[str, Any]]]] = OrderedDict()
        self._lock = threading.Lock()
        self._cold_read_lock = threading.Lock()
        # Preserve the established raw-catalogue receipt format and bounded index retention.
        self._legacy_evidence = RemoteSources(self.cache_dir, transport=transport, timeout_seconds=12.0, cache_max_entries=self.CACHE_MAX_ENTRIES)
        self.evidence_dir = self.cache_dir / "surface-observation-evidence"

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    def read_point(self, latitude: float, longitude: float, assessment_date: str) -> tuple[dict[str, Any], dict[str, Any]]:
        lat = self._coordinate(latitude, "latitude", -90, 90)
        lon = self._coordinate(longitude, "longitude", -180, 180)
        selected = self._date(assessment_date)
        key = (lat, lon, selected.isoformat())
        now_mono = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and now_mono - cached[0] <= self.CACHE_TTL_SECONDS:
                self._cache.move_to_end(key)
                return deepcopy(cached[1])
            if cached is not None:
                self._cache.pop(key, None)
        # Serialize cold reads: concurrent callers cannot multiply catalogue/COG I/O.
        with self._cold_read_lock:
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None and now_mono - cached[0] <= self.CACHE_TTL_SECONDS:
                    self._cache.move_to_end(key)
                    return deepcopy(cached[1])
            result = self._read(lat, lon, selected)
            with self._lock:
                self._cache[key] = (now_mono, deepcopy(result))
                self._cache.move_to_end(key)
                while len(self._cache) > self.CACHE_MAX_ENTRIES:
                    self._cache.popitem(last=False)
        return deepcopy(result)

    def _read(self, latitude: float, longitude: float, selected: date) -> tuple[dict[str, Any], dict[str, Any]]:
        retrieved = self._utc(self._clock())
        retrieved_at = self._stamp(retrieved)
        base = self._unknown(selected, latitude, longitude, retrieved_at)
        try:
            raw, features = self._stac(latitude, longitude, selected, retrieved)
            catalogue_digest = self._legacy_evidence._evidence("sentinel-2-l2a-catalogue", raw)
            item, observed = self._latest(features, selected, retrieved)
            if item is None:
                observation, source = base
                observation["status"] = "partial"
                source.update(status="partial", qc="partial", content_sha256=f"sha256:{catalogue_digest}", data={"extraction_scope": "scene_classification_point", "catalogue_content_sha256": f"sha256:{catalogue_digest}", "selection_limits": {"max_items": 12, "lookback_days": 10}, "asset_read": "none"})
                return observation, source
            scene_id = item.get("id")
            if not isinstance(scene_id, str) or not scene_id:
                raise ValueError("scene id missing")
            try:
                sampled = self._sample_scl(item, latitude, longitude)
            except (OSError, ValueError):
                observation, source = base
                observation.update(status="partial", observed_at=self._stamp(observed), scene_age_days=(selected - observed.date()).days, scene_id=scene_id)
                source.update(status="partial", qc="partial", observed_at=observation["observed_at"], content_sha256=f"sha256:{catalogue_digest}", data={"extraction_scope": "scene_classification_point", "catalogue_content_sha256": f"sha256:{catalogue_digest}", "selection_limits": {"max_items": 12, "lookback_days": 10}, "scene_id": scene_id, "asset_read": "unavailable"})
                return observation, source
            raw_value = sampled["raw_class"]
            status, condition = self._SCL.get(raw_value, ("partial", "unknown")) if raw_value is not None else ("partial", "unknown")
            resolution = sampled["resolution_m"]
            observation = {"status": status, "basis": "sentinel2_l2a_scl_point", "assessment_date": selected.isoformat(), "requested_point": {"latitude": latitude, "longitude": longitude}, "observed_at": self._stamp(observed), "retrieved_at": retrieved_at, "scene_age_days": (selected - observed.date()).days, "scene_id": scene_id, "scl_class": raw_value, "condition": condition, "resolution_m": resolution, "selection_scope": "bounded_catalogue_result"}
            evidence = {"collection": self.COLLECTION, "scene_id": scene_id, "observed_at": observation["observed_at"], "retrieved_at": retrieved_at, "assessment_date": selected.isoformat(), "requested_point": observation["requested_point"], "native": sampled, "catalogue_content_sha256": f"sha256:{catalogue_digest}"}
            digest = self._store_evidence(evidence)
            source = self._source(status, status, retrieved_at, observation["observed_at"], f"sha256:{digest}", {"extraction_scope": "scene_classification_point", "product": "Sentinel-2 L2A Scene Classification", "provider": "AWS Earth Search public mirror", "selection_limits": {"max_items": 12, "lookback_days": 10}, "scene_id": scene_id, "requested_point": observation["requested_point"], "assessment_date": selected.isoformat(), "catalogue_content_sha256": f"sha256:{catalogue_digest}", "native": sampled})
            return observation, source
        except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            observation, source = base
            source["data"] = {"extraction_scope": "scene_classification_point", "asset_read": "failed", "selection_limits": {"max_items": 12, "lookback_days": 10}}
            return observation, source

    def _stac(self, latitude: float, longitude: float, selected: date, retrieved: datetime) -> tuple[bytes, list[dict[str, Any]]]:
        end = min(datetime.combine(selected, daytime.max, UTC), retrieved)
        body = {"collections": [self.COLLECTION], "intersects": {"type": "Point", "coordinates": [longitude, latitude]}, "datetime": f"{(end.date() - timedelta(days=10)).isoformat()}T00:00:00Z/{self._stamp(end)}", "limit": 12, "sortby": [{"field": "properties.datetime", "direction": "desc"}]}
        with httpx.Client(transport=self.transport, timeout=12.0, follow_redirects=False) as client:
            with client.stream("POST", self.STAC_URL, json=body, headers={"Accept": "application/geo+json"}) as response:
                response.raise_for_status()
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.MAX_RESPONSE_BYTES:
                        raise ValueError("STAC response too large")
                    chunks.append(chunk)
        raw = b"".join(chunks)
        payload = json.loads(raw)
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list) or len(features) > 12:
            raise ValueError("bounded STAC features required")
        return raw, [row for row in features if isinstance(row, dict)]

    def _latest(self, features: list[dict[str, Any]], selected: date, retrieved: datetime) -> tuple[dict[str, Any] | None, datetime | None]:
        upper = min(datetime.combine(selected, daytime.max, UTC), retrieved)
        lower = datetime.combine(upper.date() - timedelta(days=10), daytime.min, UTC)
        candidates: list[tuple[datetime, dict[str, Any]]] = []
        for item in features:
            if item.get("collection") != self.COLLECTION:
                continue
            properties = item.get("properties")
            if not isinstance(properties, dict):
                continue
            value = properties.get("datetime")
            try:
                observed = self._parse_stamp(value)
            except ValueError:
                continue
            if lower <= observed <= upper:
                candidates.append((observed, item))
        return max(candidates, default=(None, None), key=lambda row: row[0]) [1], max(candidates, default=(None, None), key=lambda row: row[0]) [0]

    def _sample_scl(self, item: dict[str, Any], latitude: float, longitude: float) -> dict[str, Any]:
        import rasterio
        from rasterio.warp import transform
        from rasterio.windows import Window
        assets = item.get("assets")
        if not isinstance(assets, dict) or not isinstance(assets.get("scl"), dict):
            raise ValueError("SCL asset metadata missing")
        asset = assets["scl"]
        href = asset.get("href")
        if not isinstance(href, str) or not self._public_asset(href):
            raise ValueError("approved public SCL asset required")
        metadata_rows = asset.get("raster:bands") if isinstance(asset.get("raster:bands"), list) else []
        metadata = metadata_rows[0] if metadata_rows and isinstance(metadata_rows[0], dict) else {}
        env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff", "GDAL_HTTP_MAX_RETRY": "0", "GDAL_HTTP_TIMEOUT": "12"}
        with rasterio.Env(**env), rasterio.open(href) as dataset:
            if dataset.crs is None:
                raise ValueError("SCL CRS missing")
            xs, ys = transform("EPSG:4326", dataset.crs, [longitude], [latitude])
            row, col = dataset.index(xs[0], ys[0])
            if not 0 <= row < dataset.height or not 0 <= col < dataset.width:
                raise ValueError("point outside SCL extent")
            values = dataset.read(1, window=Window(col, row, 1, 1), masked=True)
            cell = values[0, 0]
            candidate = None if bool(getattr(cell, "mask", False)) else float(cell)
            scale = self._finite_number(metadata.get("scale", dataset.scales[0] if dataset.scales else 1.0))
            offset = self._finite_number(metadata.get("offset", dataset.offsets[0] if dataset.offsets else 0.0))
            nodata = self._finite_number(metadata.get("nodata", dataset.nodata))
            native_nodata = self._finite_number(dataset.nodata)
            # SCL codes are categorical. Any non-identity scaling is not an SCL class.
            raw_class = int(candidate) if candidate is not None and candidate not in (nodata, native_nodata) and math.isfinite(candidate) and candidate.is_integer() and 0 <= candidate <= 11 and scale == 1.0 and offset == 0.0 else None
            resolution = None
            unit = getattr(dataset.crs, "linear_units", None)
            if unit in {"metre", "meter", "m"}:
                resolution = abs(float(dataset.transform.a))
                if not math.isfinite(resolution) or resolution <= 0:
                    resolution = None
            return {"row": int(row), "col": int(col), "window": {"row": int(row), "col": int(col), "width": 1, "height": 1}, "crs": str(dataset.crs), "transform": [float(value) for value in dataset.transform[:6]], "raw_class": raw_class, "raw_value": candidate if candidate is not None and math.isfinite(candidate) else None, "nodata": nodata, "native_nodata": native_nodata, "scale": scale, "offset": offset, "resolution_m": resolution}

    def _unknown(self, selected: date, latitude: float, longitude: float, retrieved_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
        observation = {"status": "unavailable", "basis": "sentinel2_l2a_scl_point", "assessment_date": selected.isoformat(), "requested_point": {"latitude": latitude, "longitude": longitude}, "observed_at": None, "retrieved_at": retrieved_at, "scene_age_days": None, "scene_id": None, "scl_class": None, "condition": "unknown", "resolution_m": None, "selection_scope": "bounded_catalogue_result"}
        return observation, self._source("unavailable", "unavailable", retrieved_at, None, None, {"extraction_scope": "scene_classification_point"})

    def _source(self, status: str, qc: str, retrieved_at: str, observed_at: str | None, digest: str | None, data: dict[str, Any]) -> dict[str, Any]:
        return {"id": "sentinel-2-l2a", "name": "Sentinel-2", "product": "Sentinel-2 L2A Scene Classification", "version": "L2A", "status": status, "qc": qc, "note": "Scene Classification is dated observational context, not an assessment of road passability, dryness, frozen ground, or flooding.", "retrieved_at": retrieved_at, "observed_at": observed_at, "content_sha256": digest, "data": data}

    def _store_evidence(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        with self._lock:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            target = self.evidence_dir / f"{digest}.json"
            if not target.exists():
                temporary = target.with_name(f".{target.name}.{time.time_ns()}.tmp")
                try:
                    temporary.write_bytes(raw)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            for path in sorted(self.evidence_dir.glob("*.json"), key=lambda value: value.stat().st_mtime, reverse=True)[self.CACHE_MAX_ENTRIES:]:
                path.unlink(missing_ok=True)
        return digest

    @staticmethod
    def _public_asset(href: str) -> bool:
        parsed = httpx.URL(href)
        return parsed.scheme == "https" and parsed.host in RemoteSources._ASSET_HOSTS and parsed.port in (None, 443) and not parsed.userinfo and not parsed.query and not parsed.fragment and parsed.path.startswith("/sentinel-s2-l2a-cogs/") and parsed.path.lower().endswith((".tif", ".tiff"))

    @staticmethod
    def _finite_number(value: Any) -> float | None:
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coordinate(value: Any, name: str, low: float, high: float) -> float:
        number = SurfaceObservation._finite_number(value)
        if type(value) is bool or number is None or not low <= number <= high:
            raise ValueError(f"{name} must be a finite WGS84 coordinate")
        return number

    @staticmethod
    def _date(value: Any) -> date:
        if not isinstance(value, str):
            raise ValueError("assessment_date must be YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("assessment_date must be YYYY-MM-DD") from error

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _stamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _parse_stamp(value: Any) -> datetime:
        if not isinstance(value, str):
            raise ValueError("scene datetime missing")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("scene datetime timezone missing")
        return parsed.astimezone(UTC)
