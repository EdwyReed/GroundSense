"""Bounded Sentinel-2 SCL observations at existing terrain-profile points."""
from __future__ import annotations

import json
import math
import re
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, date, datetime, time as daytime, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx

from apps.api.surface_observation import SurfaceObservation


class SurfaceProfile(SurfaceObservation):
    """Read one selected SCL scene at no more than 81 supplied profile points."""

    CACHE_MAX_ENTRIES = 16

    def __init__(self, cache_dir: Path, *, transport: httpx.BaseTransport | None = None, clock: Callable[[], datetime] | None = None) -> None:
        super().__init__(cache_dir, transport=transport, clock=clock)
        self._profile_cache: OrderedDict[tuple[tuple[float, float, float], ...], tuple[float, tuple[dict[str, Any], dict[str, Any]]]] = OrderedDict()
        self.evidence_dir = self.cache_dir / "surface-profile-evidence"

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._profile_cache)

    def read_points(self, points: Any, assessment_date: str) -> tuple[dict[str, Any], dict[str, Any]]:
        rows = self._points(points)
        selected = self._date(assessment_date)
        key = tuple((row["chainage_m"], row["point"]["latitude"], row["point"]["longitude"]) for row in rows) + ((-1.0, float(selected.toordinal()), 0.0),)
        now = time.monotonic()
        with self._lock:
            cached = self._profile_cache.get(key)
            if cached is not None and now - cached[0] <= self.CACHE_TTL_SECONDS:
                self._profile_cache.move_to_end(key)
                return deepcopy(cached[1])
            self._profile_cache.pop(key, None)
        with self._cold_read_lock:
            with self._lock:
                cached = self._profile_cache.get(key)
                if cached is not None and now - cached[0] <= self.CACHE_TTL_SECONDS:
                    self._profile_cache.move_to_end(key)
                    return deepcopy(cached[1])
            result = self._read_points(rows, selected)
            with self._lock:
                self._profile_cache[key] = (now, deepcopy(result))
                self._profile_cache.move_to_end(key)
                while len(self._profile_cache) > self.CACHE_MAX_ENTRIES:
                    self._profile_cache.popitem(last=False)
        return deepcopy(result)

    def _read_points(self, points: list[dict[str, Any]], selected: date) -> tuple[dict[str, Any], dict[str, Any]]:
        from rasterio.errors import RasterioError
        retrieved = self._utc(self._clock())
        retrieved_at = self._stamp(retrieved)
        base = self._unknown_profile(points, selected, retrieved_at)
        try:
            raw, features = self._stac_line(points, selected, retrieved)
            catalogue_digest = self._legacy_evidence._evidence("sentinel-2-l2a-catalogue", raw)
            item, observed = self._latest(features, selected, retrieved)
            if item is None or observed is None:
                summary, _ = base
                summary["status"] = "partial"
                return self._bound_result(summary, [], catalogue_digest, "none")
            scene_id = item.get("id")
            if not isinstance(scene_id, str) or not scene_id:
                raise ValueError("scene id missing")
            native_samples, resolution = self._sample_scl_points(item, points)
            samples = []
            for requested, native in zip(points, native_samples):
                raw_class = native["raw_class"]
                sample_status, condition = self._SCL.get(raw_class, ("partial", "unknown")) if raw_class is not None else ("partial", "unknown")
                samples.append({"chainage_m": requested["chainage_m"], "requested_point": deepcopy(requested["point"]), "scl_class": raw_class, "condition": condition, "status": sample_status})
            status = "available" if all(row["status"] == "available" for row in samples) else "partial"
            observed_at = self._stamp(observed)
            summary = {"status": status, "basis": "sentinel2_l2a_scl_profile_points", "coverage": "discrete_points", "assessment_date": selected.isoformat(), "retrieved_at": retrieved_at, "observed_at": observed_at, "scene_id": scene_id, "scene_age_days": (selected - observed.date()).days, "resolution_m": resolution, "selection_scope": "bounded_catalogue_result", "samples": samples}
            return self._bound_result(summary, native_samples, catalogue_digest, "native_points")
        except (httpx.HTTPError, OSError, RasterioError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return base

    def _bound_result(self, summary: dict[str, Any], native_samples: list[dict[str, Any]], catalogue_digest: str, asset_read: str) -> tuple[dict[str, Any], dict[str, Any]]:
        data = {"extraction_scope": "spaced_scene_classification_points", "collection": self.COLLECTION,
                "provider": "AWS Earth Search public mirror", "selection_limits": {"max_items": 12, "lookback_days": 10},
                "assessment_date": summary["assessment_date"], "scene_id": summary["scene_id"],
                "observed_at": summary["observed_at"], "retrieved_at": summary["retrieved_at"],
                "samples": deepcopy(summary["samples"]), "native_samples": native_samples,
                "catalogue_content_sha256": f"sha256:{catalogue_digest}", "asset_read": asset_read}
        digest = f"sha256:{self._store_evidence(data)}"
        summary["source_content_sha256"] = digest
        source = self._source(summary["status"], summary["status"], summary["retrieved_at"], summary["observed_at"], digest, data)
        source["extraction_scope"] = "spaced_scene_classification_points"
        return summary, source

    def _stac_line(self, points: list[dict[str, Any]], selected: date, retrieved: datetime) -> tuple[bytes, list[dict[str, Any]]]:
        end = min(datetime.combine(selected, daytime.max, UTC), retrieved)
        coordinates = [[row["point"]["longitude"], row["point"]["latitude"]] for row in points]
        body = {"collections": [self.COLLECTION], "intersects": {"type": "LineString", "coordinates": coordinates}, "datetime": f"{(end.date() - timedelta(days=10)).isoformat()}T00:00:00Z/{self._stamp(end)}", "limit": 12, "sortby": [{"field": "properties.datetime", "direction": "desc"}]}
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

    def _sample_scl_points(self, item: dict[str, Any], points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
        import rasterio
        from rasterio.errors import RasterioError
        from rasterio.warp import transform
        assets = item.get("assets")
        if not isinstance(assets, dict):
            raise ValueError("SCL assets missing")
        asset = assets.get("scl")
        if not isinstance(asset, dict):
            raise ValueError("SCL asset metadata missing")
        href = asset.get("href")
        if not isinstance(href, str) or not self._public_asset(href):
            raise ValueError("approved public SCL asset required")
        metadata_rows = asset.get("raster:bands") if isinstance(asset.get("raster:bands"), list) else []
        metadata = metadata_rows[0] if metadata_rows and isinstance(metadata_rows[0], dict) else {}
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff", GDAL_HTTP_MAX_RETRY="0", GDAL_HTTP_TIMEOUT="12"), rasterio.open(href) as dataset:
            if dataset.crs is None or dataset.transform.b != 0 or dataset.transform.d != 0 or dataset.transform.a == 0 or dataset.transform.e == 0 or abs(abs(dataset.transform.a) - abs(dataset.transform.e)) > 1e-9:
                raise ValueError("unsupported SCL metadata")
            unit = getattr(dataset.crs, "linear_units", None)
            resolution = abs(float(dataset.transform.a)) if unit in {"metre", "meter", "m"} else None
            if resolution is None or not math.isfinite(resolution) or resolution <= 0:
                raise ValueError("SCL native scalar resolution unavailable")
            scale = self._finite_number(metadata.get("scale", dataset.scales[0] if dataset.scales else 1.0))
            offset = self._finite_number(metadata.get("offset", dataset.offsets[0] if dataset.offsets else 0.0))
            nodata = self._finite_number(metadata.get("nodata", dataset.nodata))
            native_nodata = self._finite_number(dataset.nodata)
            converted = transform("EPSG:4326", dataset.crs, [row["point"]["longitude"] for row in points], [row["point"]["latitude"] for row in points])
            xs, ys = converted[0], converted[1]
            output = []
            for row, x, y in zip(points, xs, ys):
                native = {"row": None, "col": None, "window": None, "crs": str(dataset.crs), "transform": [float(value) for value in dataset.transform[:6]], "raw_class": None, "raw_value": None, "nodata": nodata, "native_nodata": native_nodata, "scale": scale, "offset": offset, "resolution_m": resolution}
                raster_row, col = dataset.index(x, y)
                if 0 <= raster_row < dataset.height and 0 <= col < dataset.width:
                    native.update(row=int(raster_row), col=int(col), window={"row": int(raster_row), "col": int(col), "width": 1, "height": 1})
                    try:
                        cell = dataset.read(1, window=((raster_row, raster_row + 1), (col, col + 1)), masked=True)[0, 0]
                        candidate = None if bool(getattr(cell, "mask", False)) else float(cell)
                        native["raw_value"] = candidate if candidate is not None and math.isfinite(candidate) else None
                        if candidate is not None and candidate not in (nodata, native_nodata) and math.isfinite(candidate) and candidate.is_integer() and 0 <= candidate <= 11 and scale == 1.0 and offset == 0.0:
                            native["raw_class"] = int(candidate)
                    except (OSError, RasterioError):
                        pass
                output.append(native)
        return output, resolution

    def _unknown_profile(self, points: list[dict[str, Any]], selected: date, retrieved_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
        samples = [{"chainage_m": row["chainage_m"], "requested_point": deepcopy(row["point"]), "scl_class": None, "condition": "unknown", "status": "unavailable"} for row in points]
        source = self._source("unavailable", "unavailable", retrieved_at, None, None, {"extraction_scope": "spaced_scene_classification_points", "assessment_date": selected.isoformat(), "scene_id": None, "samples": deepcopy(samples)})
        source["extraction_scope"] = "spaced_scene_classification_points"
        return {"status": "unavailable", "basis": "sentinel2_l2a_scl_profile_points", "coverage": "discrete_points", "assessment_date": selected.isoformat(), "retrieved_at": retrieved_at, "observed_at": None, "scene_id": None, "scene_age_days": None, "resolution_m": None, "source_content_sha256": None, "selection_scope": "bounded_catalogue_result", "samples": samples}, source

    @staticmethod
    def _date(value: Any) -> date:
        if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise ValueError("assessment_date must be YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("assessment_date must be YYYY-MM-DD") from error

    @staticmethod
    def _points(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not 2 <= len(value) <= 81:
            raise ValueError("profile points must contain 2 through 81 points")
        output, previous = [], None
        for raw in value:
            if not isinstance(raw, dict) or set(raw) != {"chainage_m", "point"} or not isinstance(raw["point"], dict) or set(raw["point"]) != {"latitude", "longitude"}:
                raise ValueError("profile point shape invalid")
            chainage = SurfaceObservation._finite_number(raw["chainage_m"])
            if type(raw["chainage_m"]) is bool or chainage is None or chainage < 0 or (previous is not None and chainage <= previous):
                raise ValueError("profile chainages must be finite and strictly increasing")
            latitude = SurfaceObservation._coordinate(raw["point"]["latitude"], "latitude", -90, 90)
            longitude = SurfaceObservation._coordinate(raw["point"]["longitude"], "longitude", -180, 180)
            output.append({"chainage_m": chainage, "point": {"latitude": latitude, "longitude": longitude}})
            previous = chainage
        if output[0]["chainage_m"] != 0 or output[-1]["chainage_m"] > 20_000:
            raise ValueError("profile chainage bounds invalid")
        return output
