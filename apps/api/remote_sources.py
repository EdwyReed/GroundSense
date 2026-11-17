"""Honest, bounded adapters for public environmental-source reads."""
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


class RemoteSources:
    """Read public model data and Sentinel-2 COG pixels without credentials."""

    ERA5_LAND_URL = "https://archive-api.open-meteo.com/v1/archive"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    STAC_URL = "https://earth-search.aws.element84.com/v1/search"
    ERA5_VARIABLES = ("temperature_2m", "precipitation", "soil_temperature_0_to_7cm", "soil_moisture_0_to_7cm", "soil_temperature_7_to_28cm", "soil_moisture_7_to_28cm")
    FORECAST_VARIABLES = ("temperature_2m", "precipitation", "soil_moisture_0_to_1cm")
    FORECAST_MODELS = (
        ("ecmwf-ifs", "ECMWF IFS via Open-Meteo", "ecmwf_ifs025", FORECAST_VARIABLES),
        ("ecmwf-aifs", "ECMWF AIFS via Open-Meteo", "ecmwf_aifs025_single", FORECAST_VARIABLES),
        # Open-Meteo returns an undefined unit for this GFS soil field, so request only verified variables.
        ("noaa-gfs", "NOAA GFS via Open-Meteo", "gfs_seamless", ("temperature_2m", "precipitation")),
    )
    _FORECAST_UNITS = {"temperature_2m": "°C", "precipitation": "mm", "soil_moisture_0_to_1cm": "m³/m³"}
    _SOURCE_KEYS = ("id", "name", "product", "version", "status", "qc", "note", "retrieved_at", "observed_at", "content_sha256", "data")
    _COLLECTIONS = {"sentinel_1": "sentinel-1-grd", "sentinel_2": "sentinel-2-l2a"}
    _ASSET_HOSTS = {"sentinel-cogs.s3.us-west-2.amazonaws.com", "sentinel-cogs.s3.amazonaws.com"}

    def __init__(self, cache_dir: Path, *, transport: httpx.BaseTransport | None = None, timeout_seconds: float = 12.0, cache_max_entries: int = 64) -> None:
        if timeout_seconds <= 0 or cache_max_entries < 1:
            raise ValueError("timeout_seconds must be positive and cache_max_entries at least one")
        self.cache_dir = Path(cache_dir)
        self.raw_dir = self.cache_dir / "raw"
        self.index_dir = self.cache_dir / "indexes"
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.cache_max_entries = cache_max_entries
        self._read_cached = lru_cache(maxsize=cache_max_entries)(self._read)

    def read(self, latitude: float, longitude: float, assessment_date: str) -> dict[str, Any]:
        lat, lon, selected = self._coordinate(latitude, -90, 90, "latitude"), self._coordinate(longitude, -180, 180, "longitude"), self._date(assessment_date)
        # Fixed five-minute cache windows preserve the original retrieval time.
        # Copy returned records so a caller cannot alter cached provenance/data.
        return deepcopy(self._read_cached(lat, lon, selected, int(time.monotonic() // 300)))

    def _read(self, lat: float, lon: float, selected: date, _cache_window: int) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        history, era_source = self._era5_land(lat, lon, selected, now)
        satellites, sentinel_sources = {}, []
        for key, collection in self._COLLECTIONS.items():
            satellite, source = self._sentinel(key, collection, lat, lon, selected, now)
            satellites[key], sentinel_sources = satellite, [*sentinel_sources, source]
        forecasts = [self._forecast(identifier, product, model, variables, lat, lon, selected, now) for identifier, product, model, variables in self.FORECAST_MODELS]
        return {"satellites": satellites, "history": history, "sources": [era_source, *sentinel_sources, *forecasts, *self._catalogue_sources(now)]}

    def _era5_land(self, lat: float, lon: float, selected: date, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
        params = {"latitude": self._number(lat), "longitude": self._number(lon), "start_date": selected.isoformat(), "end_date": selected.isoformat(), "hourly": ",".join(self.ERA5_VARIABLES), "models": "era5_land", "timezone": "UTC"}
        try:
            raw = self._request("GET", self.ERA5_LAND_URL, params=params)
            payload = json.loads(raw)
            series, units, grid = self._parse_era5(payload)
            for row in series:
                row["time"] = self._timestamp(row["time"], selected)
            qc = self._numeric_qc(series, self.ERA5_VARIABLES)
            if qc == "unavailable":
                series = []
            digest = self._evidence("era5-land", raw)
            note = "Отримано погодинні модельні значення, не вимірювання дороги." if qc == "available" else ("Частина модельних значень відсутня." if qc == "partial" else "Відповідь містить лише null: числові дані відсутні.")
            source = self._source("era5-land", "Copernicus / ECMWF", "ERA5-Land via Open-Meteo archive mirror", "era5_land", qc, qc, note, now, series[0]["time"] if series else None, digest, {"units": units, "grid_point": grid, "series_count": len(series), "extraction": "numerical" if series else "none", "provenance": "Open-Meteo archive mirror, not a direct Copernicus read"})
            return {"source_id": "era5-land", "units": units, "grid_point": grid, "series": series, "note": "ERA5-Land is a reanalysis/model estimate at grid scale, not a measured road property."}, source
        except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            source = self._source("era5-land", "Copernicus / ECMWF", "ERA5-Land via Open-Meteo archive mirror", "era5_land", "unavailable", "unavailable", f"Не вдалося отримати числовий історичний ряд: {self._error(exc)}", now, None, None, {"extraction": "none"})
            return {"source_id": "era5-land", "units": {}, "grid_point": None, "series": [], "note": "No synthetic replacement was used."}, source

    def _sentinel(self, key: str, collection: str, lat: float, lon: float, selected: date, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
        bbox = [round(lon - .005, 6), round(lat - .005, 6), round(lon + .005, 6), round(lat + .005, 6)]
        window_start, window_end = selected - timedelta(days=10), selected
        body = {"collections": [collection], "bbox": bbox, "datetime": f"{window_start.isoformat()}T00:00:00Z/{window_end.isoformat()}T23:59:59Z", "limit": 100}
        source_id, product = ("sentinel-1-grd", "Sentinel-1 GRD") if key == "sentinel_1" else ("sentinel-2-l2a", "Sentinel-2 L2A")
        try:
            raw = self._request("POST", self.STAC_URL, json=body)
            features = json.loads(raw).get("features")
            if not isinstance(features, list):
                raise ValueError("STAC features missing")
            item = self._nearest_earlier(features, selected)
            digest = self._evidence(source_id, raw)
            if item is None:
                note = "У каталозі немає сцени за 10 днів до обраної UTC-дати; значення пікселя не підставлялися."
                return {"status": "partial", "item": None, "note": note}, self._source(source_id, "AWS Earth Search public mirror", product, "STAC 1.0", "partial", "partial", note, now, None, digest, {"discovery": "actual_stac", "item": None, "asset_read": "none"})
            descriptor = self._item_descriptor(item, key)
            if key != "sentinel_2":
                note = "Знайдено лише запис каталогу; значення SAR та його попередня обробка не заявляються."
                return {"status": "partial", "item": descriptor, "scene_age_days": self._age_days(descriptor["observed_at"], selected), "note": note}, self._source(source_id, "AWS Earth Search public mirror", product, "STAC 1.0", "partial", "partial", note, now, descriptor["observed_at"], digest, {"discovery": "actual_stac", "item": descriptor, "asset_read": "none"})
            try:
                pixel, pixel_raw = self._decode_sentinel2(item, lat, lon)
            except (ValueError, OSError) as exc:
                note = f"Запис каталогу знайдено, але піксель публічного COG не прочитано: {self._error(exc)}"
                return {"status": "partial", "item": descriptor, "scene_age_days": self._age_days(descriptor["observed_at"], selected), "note": note}, self._source(source_id, "AWS Earth Search public mirror", product, "STAC 1.0", "partial", "partial", note, now, descriptor["observed_at"], digest, {"discovery": "actual_stac", "item": descriptor, "asset_read": "none"})
            pixel_digest = self._evidence("sentinel-2-pixel", pixel_raw)
            age = self._age_days(descriptor["observed_at"], selected)
            note = "Зчитано вікно пікселів Sentinel-2 L2A COG у запитаній точці WGS84; коефіцієнт відбиття приведено до одиниць джерела. Це не вимірювання дороги."
            data = {"discovery": "actual_stac", "item": descriptor, "pixel": pixel, "pixel_content_sha256": f"sha256:{pixel_digest}", "extraction": "rasterio_cog_window"}
            return {"status": "available", "item": descriptor, "scene_age_days": age, "pixel": pixel, "note": note}, self._source(source_id, "AWS Earth Search public mirror", product, "L2A COG/STAC", "available", pixel["qc"]["status"], note, now, descriptor["observed_at"], pixel_digest, data)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError, OSError) as exc:
            note = f"Не вдалося прочитати каталог або растр: {self._error(exc)}"
            return {"status": "unavailable", "item": None, "note": note}, self._source(source_id, "AWS Earth Search public mirror", product, "STAC 1.0", "unavailable", "unavailable", note, now, None, None, {"discovery": "none", "asset_read": "none"})

    def _decode_sentinel2(self, item: dict[str, Any], latitude: float, longitude: float) -> tuple[dict[str, Any], bytes]:
        import rasterio
        from rasterio.transform import rowcol
        from rasterio.warp import transform
        from rasterio.windows import Window

        assets = item.get("assets")
        if not isinstance(assets, dict):
            raise ValueError("Sentinel-2 assets missing")
        bands: dict[str, Any] = {}
        sample_window: dict[str, int] | None = None
        for name in ("blue", "green", "red", "nir", "scl"):
            asset = assets.get(name)
            href = asset.get("href") if isinstance(asset, dict) else None
            if not isinstance(href, str) or not self._public_cog(href):
                raise ValueError(f"public Sentinel-2 {name} COG unavailable")
            metadata = asset.get("raster:bands") if isinstance(asset.get("raster:bands"), list) else []
            metadata = metadata[0] if metadata and isinstance(metadata[0], dict) else {}
            with rasterio.open(href) as dataset:
                xs, ys = transform("EPSG:4326", dataset.crs, [longitude], [latitude])
                row, col = rowcol(dataset.transform, xs[0], ys[0])
                window = Window(max(0, col - 1), max(0, row - 1), min(3, dataset.width - max(0, col - 1)), min(3, dataset.height - max(0, row - 1)))
                values = dataset.read(1, window=window, masked=True)
                center = values[min(1, values.shape[0] - 1), min(1, values.shape[1] - 1)]
                nodata = metadata.get("nodata", dataset.nodata)
                scale = float(metadata.get("scale", dataset.scales[0] if dataset.scales else 1.0))
                offset = float(metadata.get("offset", dataset.offsets[0] if dataset.offsets else 0.0))
                raw_value = None if values.mask[min(1, values.shape[0] - 1), min(1, values.shape[1] - 1)] else float(center)
                unit = "SCL_class" if name == "scl" else "reflectance"
                value = raw_value if name == "scl" or raw_value is None else raw_value * scale + offset
                bands[name] = {"value": int(value) if name == "scl" and value is not None else value, "raw_value": raw_value, "unit": unit, "scale": scale, "offset": offset, "nodata": nodata}
                sample_window = {"row": int(window.row_off), "col": int(window.col_off), "width": int(window.width), "height": int(window.height)}
        scl = bands["scl"]["value"]
        flagged = scl in {3, 8, 9, 10, 11}
        result = {"bands": bands, "scl": {"value": scl, "unit": "SCL_class", "cloud_shadow_snow_classes": [3, 8, 9, 10, 11]}, "window": sample_window, "qc": {"status": "partial" if flagged or scl is None else "available", "cloud_or_shadow_or_snow": flagged, "basis": "Sentinel-2 L2A SCL center pixel"}}
        return result, json.dumps(result, sort_keys=True, separators=(",", ":")).encode()

    def _forecast(self, identifier: str, product: str, model: str, variables: tuple[str, ...], lat: float, lon: float, selected: date, now: str) -> dict[str, Any]:
        expected_units = {variable: self._FORECAST_UNITS[variable] for variable in variables}
        params = {"latitude": self._number(lat), "longitude": self._number(lon), "hourly": ",".join(variables), "models": model, "start_date": selected.isoformat(), "end_date": selected.isoformat(), "timezone": "UTC"}
        try:
            raw = self._request("GET", self.FORECAST_URL, params=params)
            payload = json.loads(raw)
            units, hourly = payload.get("hourly_units"), payload.get("hourly")
            if not isinstance(units, dict) or not isinstance(hourly, dict) or any(units.get(k) != v for k, v in expected_units.items()):
                raise ValueError("unexpected forecast variables or units")
            times = hourly.get("time")
            if not isinstance(times, list) or not times:
                raise ValueError("forecast time series missing")
            series = []
            for index, timestamp in enumerate(times):
                row = {"time": self._timestamp(timestamp, selected)}
                for variable in variables:
                    values = hourly.get(variable)
                    if not isinstance(values, list) or len(values) != len(times) or (values[index] is not None and not self._finite(values[index])):
                        raise ValueError(f"invalid forecast {variable}")
                    row[variable] = None if values[index] is None else float(values[index])
                series.append(row)
            digest = self._evidence(identifier, raw)
            provenance = "Open-Meteo model mirror; free non-commercial prototype, not a direct provider read"
            qc = self._numeric_qc(series, variables)
            if qc == "unavailable":
                series = []
            note = "Числовий прогноз через Open-Meteo; безкоштовний API лише для некомерційного прототипу." if qc == "available" else ("Частина прогнозних значень відсутня." if qc == "partial" else "Відповідь містить лише null: числовий прогноз відсутній.")
            return self._source(identifier, "Open-Meteo", product, model, qc, qc, note, now, series[0]["time"] if series else None, digest, {"model": model, "variables": list(variables), "units": expected_units, "series": series, "provenance": provenance, "direct_provider": False})
        except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return self._source(identifier, "Open-Meteo", product, model, "unavailable", "unavailable", f"Не вдалося прочитати дзеркало прогнозу: {self._error(exc)}", now, None, None, {"model": model, "extraction": "none", "provenance": "Open-Meteo model mirror; not a direct provider read"})

    def _catalogue_sources(self, now: str) -> list[dict[str, Any]]:
        items = [
            ("clms-swi-1km-v2", "Copernicus Land Monitoring Service", "Daily Soil Water Index Europe 1 km v2", "v2", "partial", "partial", "product metadata only; CDSE account/access path and coverage/tile must be verified before numerical extraction"),
            ("clms-ssm-1km", "Copernicus Land Monitoring Service", "Surface Soil Moisture 1 km", None, "partial", "partial", "product metadata only; selected product version, coverage and asset access remain unverified"),
            ("openstreetmap", "OpenStreetMap / Geofabrik", "OSM road-network context", None, "partial", "partial", "metadata-only; fixed PBF snapshot/local import required; OSM is not complete road truth"),
            ("hwsd-v2", "FAO / IIASA", "Harmonized World Soil Database v2", "v2.0", "auth_required", "unavailable", "dataset-specific commercial reuse clearance is required before ingestion"),
            ("esdac-ukraine-soil-map", "European Commission JRC", "Soil Map of Ukraine (1977)", "1977", "partial", "unavailable", "historical scan metadata only; georeferencing, legend and reuse rights are not verified"),
            ("corine-land-cover", "Copernicus Land Monitoring Service", "CORINE Land Cover", "2018", "partial", "unavailable", "historical contextual catalogue only; coverage/tile must be checked for the point"),
            ("clms-tree-cover-density", "Copernicus Land Monitoring Service", "High Resolution Layer Tree Cover Density", "2018", "partial", "unavailable", "metadata-only; EEA38 coverage does not establish Ukraine availability"),
        ]
        return [self._source(i, n, p, v, status, qc, note, now, None, None, {"extraction": "metadata_only"}) for i, n, p, v, status, qc, note in items]

    def _request(self, method: str, url: str, **kwargs: Any) -> bytes:
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = client.request(method, url, headers={"Accept": "application/json", **kwargs.pop("headers", {})}, **kwargs)
        response.raise_for_status()
        return response.content

    def _evidence(self, provider: str, raw: bytes) -> str:
        digest = hashlib.sha256(raw).hexdigest(); self.raw_dir.mkdir(parents=True, exist_ok=True)
        target = self.raw_dir / f"{digest}.bin"
        if not target.exists(): self._atomic(target, raw)
        self.index_dir.mkdir(parents=True, exist_ok=True); key = hashlib.sha256(f"{provider}:{digest}".encode()).hexdigest()
        self._atomic(self.index_dir / f"{key}.json", json.dumps({"provider": provider, "digest": digest}, separators=(",", ":")).encode())
        for path in sorted(self.index_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[self.cache_max_entries:]: path.unlink(missing_ok=True)
        return digest

    @staticmethod
    def _atomic(path: Path, data: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
        try: temporary.write_bytes(data); temporary.replace(path)
        finally: temporary.unlink(missing_ok=True)

    @classmethod
    def _parse_era5(cls, payload: Any) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, float]]:
        if not isinstance(payload, dict) or payload.get("utc_offset_seconds") not in (0, None): raise ValueError("unexpected ERA5 response")
        units, hourly = payload.get("hourly_units"), payload.get("hourly")
        required = {"temperature_2m": "°C", "precipitation": "mm", "soil_temperature_0_to_7cm": "°C", "soil_moisture_0_to_7cm": "m³/m³", "soil_temperature_7_to_28cm": "°C", "soil_moisture_7_to_28cm": "m³/m³"}
        times = hourly.get("time") if isinstance(hourly, dict) else None
        if not isinstance(units, dict) or units.get("time") != "iso8601" or any(units.get(k) != v for k, v in required.items()) or not isinstance(times, list) or not times: raise ValueError("missing ERA5 schema")
        series = []
        for index, timestamp in enumerate(times):
            row = {"time": f"{timestamp}Z" if isinstance(timestamp, str) and not timestamp.endswith("Z") else timestamp}
            for variable in cls.ERA5_VARIABLES:
                values = hourly.get(variable)
                if not isinstance(values, list) or len(values) != len(times) or (values[index] is not None and not cls._finite(values[index])): raise ValueError(f"invalid ERA5 {variable}")
                row[variable] = None if values[index] is None else float(values[index])
            series.append(row)
        return series, required, {"latitude": float(payload["latitude"]), "longitude": float(payload["longitude"])}

    @staticmethod
    def _numeric_qc(series: list[dict[str, Any]], variables: tuple[str, ...]) -> str:
        values = [row.get(variable) for row in series for variable in variables]
        if not any(value is not None for value in values):
            return "unavailable"
        return "partial" if any(value is None for value in values) else "available"

    @staticmethod
    def _timestamp(value: Any, selected: date) -> str:
        if not isinstance(value, str):
            raise ValueError("source timestamp missing")
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        if stamp.utcoffset() != timedelta(0) or stamp.date() != selected:
            raise ValueError("source timestamp outside selected UTC day")
        return stamp.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _nearest_earlier(features: list[Any], selected: date) -> dict[str, Any] | None:
        cutoff = datetime.combine(selected + timedelta(days=1), datetime.min.time(), UTC)
        candidates = []
        for item in features:
            if isinstance(item, dict):
                stamp = (item.get("properties") or {}).get("datetime")
                if isinstance(stamp, str):
                    try:
                        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)
                        if observed < cutoff: candidates.append((observed, item))
                    except ValueError: pass
        return max(candidates, default=(None, None), key=lambda pair: pair[0])[1]

    @staticmethod
    def _item_descriptor(item: dict[str, Any], key: str) -> dict[str, Any]:
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        result = {"id": item.get("id"), "collection": item.get("collection"), "observed_at": properties.get("datetime"), "cloud_cover": properties.get("eo:cloud_cover")}
        if key == "sentinel_1": result.update(instrument_mode=properties.get("sar:instrument_mode"), polarizations=properties.get("sar:polarizations"))
        return result

    @staticmethod
    def _age_days(observed_at: Any, selected: date) -> int | None:
        try: return (selected - datetime.fromisoformat(str(observed_at).replace("Z", "+00:00")).date()).days
        except ValueError: return None

    @classmethod
    def _source(cls, identifier: str, name: str, product: str, version: str | None, status: str, qc: str, note: str, retrieved_at: str, observed_at: str | None, digest: str | None, data: dict[str, Any]) -> dict[str, Any]:
        result = {"id": identifier, "name": name, "product": product, "version": version, "status": status, "qc": qc, "note": note, "retrieved_at": retrieved_at, "observed_at": observed_at, "content_sha256": f"sha256:{digest}" if digest else None, "data": data}; assert tuple(result) == cls._SOURCE_KEYS; return result

    @staticmethod
    def _public_cog(href: str) -> bool:
        parsed = httpx.URL(href); return parsed.scheme == "https" and parsed.host in RemoteSources._ASSET_HOSTS and not parsed.query
    @staticmethod
    def _finite(value: Any) -> bool: return type(value) in (int, float) and math.isfinite(float(value))
    @staticmethod
    def _coordinate(value: Any, low: float, high: float, name: str) -> float:
        if not RemoteSources._finite(value) or not low <= float(value) <= high: raise ValueError(f"{name} must be finite and within WGS84 bounds")
        return float(value)
    @staticmethod
    def _date(value: str) -> date:
        if not isinstance(value, str): raise ValueError("assessment_date must be YYYY-MM-DD")
        try: return date.fromisoformat(value)
        except ValueError as exc: raise ValueError("assessment_date must be YYYY-MM-DD") from exc
    @staticmethod
    def _number(value: float) -> str: return format(value, ".8f").rstrip("0").rstrip(".")
    @staticmethod
    def _error(error: BaseException) -> str: return type(error).__name__
