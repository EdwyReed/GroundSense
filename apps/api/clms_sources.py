"""Bounded point reads for the exact CLMS European 1 km moisture products."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import tempfile
import time
import zipfile
from copy import deepcopy
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import httpx


class CLMSSources:
    """Read selected-day CLMS SWI v2 and SSM v1 rasters through CDSE OData.

    CDSE permits catalogue discovery without a token, but product downloads require
    a bearer token.  ``token_provider`` is deliberately injected: this adapter does
    not read credentials, environment variables, or signed URLs.
    """

    CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
    DOWNLOAD_BASE_URL = "https://download.dataspace.copernicus.eu/odata/v1/Products"
    _MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
    _MAX_CATALOGUE_BYTES = 1024 * 1024
    _MAX_ZIP_MEMBERS = 64
    _MAX_MEMBER_BYTES = 128 * 1024 * 1024
    _MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
    _MAX_COMPRESSION_RATIO = 1000
    _SOURCE_KEYS = ("id", "name", "product", "version", "status", "qc", "note", "retrieved_at", "observed_at", "content_sha256", "data")
    _PRODUCTS = (
        ("swi", "clms-swi-1km-v2", "Daily Soil Water Index Europe 1 km v2", "swi_europe_1km_daily_v2", "SWI"),
        ("ssm", "clms-ssm-1km", "Surface Soil Moisture Europe 1 km v1", "ssm_europe_1km_daily_v1", "SSM"),
    )

    def __init__(self, cache_dir: Path, *, token_provider: Callable[[], str | None] | None = None, transport: httpx.BaseTransport | None = None, timeout_seconds: float = 20.0, cache_max_entries: int = 32) -> None:
        if timeout_seconds <= 0 or cache_max_entries < 1:
            raise ValueError("timeout_seconds must be positive and cache_max_entries at least one")
        self.cache_dir = Path(cache_dir)
        self.raw_dir = self.cache_dir / "raw"
        self.index_dir = self.cache_dir / "indexes"
        self.token_provider = token_provider
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.cache_max_entries = cache_max_entries
        self._read_cached = lru_cache(maxsize=cache_max_entries)(self._read)

    @classmethod
    def download_url(cls, product_id: str) -> str:
        return f"{cls.DOWNLOAD_BASE_URL}({product_id})/$value"

    def read(self, latitude: float, longitude: float, assessment_date: str) -> dict[str, Any]:
        lat = self._coordinate(latitude, -90, 90, "latitude")
        lon = self._coordinate(longitude, -180, 180, "longitude")
        selected = self._date(assessment_date)
        return deepcopy(self._read_cached(lat, lon, selected, int(time.monotonic() // 300)))

    def _read(self, latitude: float, longitude: float, selected: date, _cache_window: int) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        result: dict[str, Any] = {"soil_moisture": {"swi": None, "ssm": None}, "sources": []}
        for key, identifier, product, dataset, variable in self._PRODUCTS:
            point, source = self._product(key, identifier, product, dataset, variable, latitude, longitude, selected, now)
            result["soil_moisture"][key] = point
            result["sources"].append(source)
        return result

    def _product(self, key: str, identifier: str, product: str, dataset: str, variable: str, latitude: float, longitude: float, selected: date, now: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        try:
            item, catalogue_raw = self._catalogue(dataset, selected)
            catalogue_digest = self._evidence(f"{identifier}-catalogue", catalogue_raw)
            if item is None:
                note = "За обрану UTC-добу продукт у публічному каталозі CDSE відсутній; попередню дату не підставлено."
                return None, self._source(identifier, "Copernicus Land Monitoring Service", product, None, "unavailable", "unavailable", note, now, None, catalogue_digest, {"dataset_identifier": dataset, "selected_utc_date": selected.isoformat(), "extraction": "none", "catalogue": "queried"})
            version = self._attribute(item, "productVersion")
            observed = self._observed_at(item, selected)
            token = self.token_provider() if self.token_provider else None
            if not isinstance(token, str) or not token.strip():
                note = "Каталог CDSE знайдено, але для завантаження растра потрібен інʼєктований bearer token CDSE; числове значення не заявлено."
                return None, self._source(identifier, "Copernicus Land Monitoring Service", product, version, "auth_required", "unavailable", note, now, observed, catalogue_digest, {"dataset_identifier": dataset, "selected_utc_date": selected.isoformat(), "product_id": item.get("Id"), "extraction": "none", "access_url": "https://documentation.dataspace.copernicus.eu/APIs/Token.html"})
            raw = self._request("GET", self.download_url(str(item["Id"])), maximum_bytes=self._MAX_DOWNLOAD_BYTES, headers={"Authorization": f"Bearer {token.strip()}", "Accept": "application/octet-stream"})
            digest = self._evidence(identifier, raw)
            point = self._sample_zip(raw, variable, latitude, longitude, key)
            if point is None:
                note = "Растр отримано, але значення точки є NoData або поза покриттям; нуль не підставлено."
                return None, self._source(identifier, "Copernicus Land Monitoring Service", product, version, "unavailable", "unavailable", note, now, observed, digest, {"dataset_identifier": dataset, "selected_utc_date": selected.isoformat(), "product_id": item.get("Id"), "extraction": "rasterio_zip_point", "no_data": True})
            point["observed_at"] = observed
            point["product_version"] = version
            note = "Отримано числове значення з растра CDSE у запитаній точці та обрану UTC-добу. SWI depth_index — характеристичний час T (дні), не фізична глибина."
            qc = point["qc"]["status"]
            if not point['unit_known']:
                note += " Одиницю в метаданих растра не оголошено; значення не трактуємо як відсоток."
            return point, self._source(identifier, "Copernicus Land Monitoring Service", product, version, "available" if point['unit_known'] else "partial", qc, note, now, observed, digest, {"dataset_identifier": dataset, "selected_utc_date": selected.isoformat(), "product_id": item.get("Id"), "extraction": "rasterio_zip_point", "point": point})
        except httpx.HTTPStatusError as exc:
            status = "auth_required" if exc.response.status_code in (401, 403) else "unavailable"
            note = "CDSE відхилив доступ до растра: потрібен чинний bearer token." if status == "auth_required" else f"Зчитування CLMS не виконано: HTTP {exc.response.status_code}."
            return None, self._source(identifier, "Copernicus Land Monitoring Service", product, None, status, "unavailable", note, now, None, None, {"dataset_identifier": dataset, "selected_utc_date": selected.isoformat(), "extraction": "none", "access_url": "https://documentation.dataspace.copernicus.eu/APIs/Token.html" if status == "auth_required" else None})
        except (httpx.HTTPError, ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
            return None, self._source(identifier, "Copernicus Land Monitoring Service", product, None, "unavailable", "unavailable", f"Зчитування CLMS не виконано: {type(exc).__name__}.", now, None, None, {"dataset_identifier": dataset, "selected_utc_date": selected.isoformat(), "extraction": "none"})

    def _catalogue(self, dataset: str, selected: date) -> tuple[dict[str, Any] | None, bytes]:
        start = f"{selected.isoformat()}T00:00:00.000Z"
        end = f"{selected.isoformat()}T23:59:59.999Z"
        filter_value = ("Collection/Name eq 'CLMS' and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'datasetIdentifier' "
                        f"and att/OData.CSC.StringAttribute/Value eq '{dataset}') and ContentDate/End ge {start} and ContentDate/Start le {end}")
        raw = self._request("GET", self.CATALOGUE_URL, params={"$filter": filter_value, "$top": "8", "$orderby": "ContentDate/Start desc", "$expand": "Attributes"})
        values = json.loads(raw).get("value")
        if not isinstance(values, list):
            raise ValueError("CLMS catalogue schema missing")
        cog = [item for item in values if isinstance(item, dict) and self._attribute(item, "fileFormat") == "cog" and self._nominal_date(item) == selected]
        return (cog[0] if cog else None), raw

    def _sample_zip(self, raw: bytes, variable: str, latitude: float, longitude: float, key: str) -> dict[str, Any] | None:
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.transform import rowcol

        if len(raw) > self._MAX_DOWNLOAD_BYTES:
            raise ValueError("CLMS ZIP exceeds download size limit")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > self._MAX_ZIP_MEMBERS or sum(item.file_size for item in members) > self._MAX_UNCOMPRESSED_BYTES:
                raise ValueError("CLMS ZIP exceeds member count or expanded size limit")
            if any(item.file_size > self._MAX_MEMBER_BYTES or item.file_size / max(1, item.compress_size) > self._MAX_COMPRESSION_RATIO for item in members):
                raise ValueError("CLMS ZIP exceeds member size or compression ratio limit")
            names = [item.filename for item in members if not item.is_dir() and item.filename.lower().endswith((".tif", ".tiff"))]
            value_name = next((name for name in names if re.search(rf"(?:_|-){variable}(?:\d{{3}})?(?:_|-|\.)", Path(name).name, re.I)), None)
            if value_name is None:
                raise ValueError(f"{variable} raster missing")
            quality_name = next((name for name in names if re.search(r"(?:_|-)QFLAG(?:_|-|\.)", Path(name).name, re.I)), None)
            value = self._sample_tiff(MemoryFile(archive.read(value_name)), latitude, longitude)
            if value is None:
                return None
            quality = self._sample_tiff(MemoryFile(archive.read(quality_name)), latitude, longitude) if quality_name else None
        raw_value, tags, nodata, scale, offset = value
        actual = raw_value * scale + offset
        depth_match = re.search(r"(?:_|-)(SWI\d{3})(?:_|-|\.)", Path(value_name).name, re.I)
        depth_index = depth_match.group(1).upper() if key == "swi" and depth_match else None
        unit = tags.get("units") or tags.get("unit") or None
        qc_value = quality[0] if quality else None
        return {"value": actual, "raw_value": raw_value, "unit": unit, "unit_known":unit is not None, "scale_factor": scale, "add_offset": offset, "nodata": nodata, "depth_index": depth_index, "qc": {"status": "partial" if qc_value is not None else "unavailable", "raw_value": qc_value, "variable": "QFLAG" if quality_name else None, "semantics": "Неінтерпретований raw QFLAG з цього продукту; біти не перетворюються на добрий/поганий без product-specific legend."}}

    @staticmethod
    def _sample_tiff(memory: Any, latitude: float, longitude: float) -> tuple[float, dict[str, str], float | int | None, float, float] | None:
        import rasterio
        from rasterio.transform import rowcol
        from rasterio.warp import transform
        with memory as mem, mem.open() as raster:
            if raster.crs is None:
                raise ValueError('CLMS raster CRS missing')
            xs, ys = transform('EPSG:4326',raster.crs,[longitude],[latitude])
            row, col = rowcol(raster.transform, xs[0], ys[0])
            if not (0 <= row < raster.height and 0 <= col < raster.width):
                return None
            pixel = raster.read(1, window=rasterio.windows.Window(col, row, 1, 1), masked=True)[0, 0]
            if bool(getattr(pixel, "mask", False)):
                return None
            raw = float(pixel)
            tags = {str(k).lower(): str(v) for k, v in {**raster.tags(),**raster.tags(1)}.items()}
            if raster.units[0] and not (tags.get('units') or tags.get('unit')):
                tags['units'] = raster.units[0]
            scale = float(tags.get("scale_factor", raster.scales[0] if raster.scales else 1.0))
            offset = float(tags.get("add_offset", raster.offsets[0] if raster.offsets else 0.0))
            return raw, tags, raster.nodata, scale, offset

    def _request(self, method: str, url: str, *, maximum_bytes: int = _MAX_CATALOGUE_BYTES, **kwargs: Any) -> bytes:
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as output:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds, follow_redirects=False) as client:
                with client.stream(method, url, **kwargs) as response:
                    response.raise_for_status()
                    length = response.headers.get("content-length")
                    if length is not None and (not length.isdigit() or int(length) > maximum_bytes):
                        raise ValueError("CLMS response exceeds bounded download size")
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > maximum_bytes:
                            raise ValueError("CLMS response exceeds bounded download size")
                        output.write(chunk)
            output.seek(0)
            return output.read()

    def _evidence(self, provider: str, raw: bytes) -> str:
        digest = hashlib.sha256(raw).hexdigest()
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        target = self.raw_dir / f"{digest}.bin"
        if not target.exists():
            self._atomic(target, raw)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(f"{provider}:{digest}".encode()).hexdigest()
        self._atomic(self.index_dir / f"{key}.json", json.dumps({"provider": provider, "digest": digest}, separators=(",", ":")).encode())
        for path in sorted(self.index_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[self.cache_max_entries:]:
            path.unlink(missing_ok=True)
        return digest

    @staticmethod
    def _atomic(path: Path, data: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _attribute(item: dict[str, Any], name: str) -> str | None:
        attributes = item.get("Attributes")
        if isinstance(attributes, list):
            for attribute in attributes:
                if isinstance(attribute, dict) and attribute.get("Name") == name and attribute.get("Value") is not None:
                    return str(attribute["Value"])
        return None

    @classmethod
    def _nominal_date(cls, item: dict[str, Any]) -> date | None:
        value = cls._attribute(item, "nominalDate")
        if not isinstance(value, str):
            content = item.get("ContentDate")
            value = content.get("Start") if isinstance(content, dict) else None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC).date()
        except ValueError:
            return None

    @classmethod
    def _observed_at(cls, item: dict[str, Any], selected: date) -> str:
        value = cls._attribute(item, "nominalDate")
        if not isinstance(value, str):
            content = item.get("ContentDate")
            value = content.get("Start") if isinstance(content, dict) else None
        if not isinstance(value, str):
            return f"{selected.isoformat()}T00:00:00Z"
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        if parsed.date() != selected:
            raise ValueError("catalogue product outside selected UTC date")
        return parsed.isoformat().replace("+00:00", "Z")

    @classmethod
    def _source(cls, identifier: str, name: str, product: str, version: str | None, status: str, qc: str, note: str, retrieved_at: str, observed_at: str | None, digest: str | None, data: dict[str, Any]) -> dict[str, Any]:
        result = {"id": identifier, "name": name, "product": product, "version": version, "status": status, "qc": qc, "note": note, "retrieved_at": retrieved_at, "observed_at": observed_at, "content_sha256": f"sha256:{digest}" if digest else None, "data": data}
        assert tuple(result) == cls._SOURCE_KEYS
        return result

    @staticmethod
    def _finite(value: Any) -> bool:
        return type(value) in (int, float) and math.isfinite(float(value))

    @classmethod
    def _coordinate(cls, value: Any, lower: float, upper: float, name: str) -> float:
        if not cls._finite(value) or not lower <= float(value) <= upper:
            raise ValueError(f"{name} must be finite and within WGS84 bounds")
        return float(value)

    @staticmethod
    def _date(value: str) -> date:
        if not isinstance(value, str):
            raise ValueError("assessment_date must be YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("assessment_date must be YYYY-MM-DD") from exc
