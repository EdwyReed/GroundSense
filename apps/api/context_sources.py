"""Bounded, provenance-preserving reads for historical and land-cover context.

These sources describe static or historical context only.  They do not infer road
conditions, and a catalogue or scan is never promoted to a point soil value.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from copy import deepcopy
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx


class ContextSources:
    """Read fixed public identify/metadata endpoints without credentials."""

    CLC_IDENTIFY_URL = "https://image.discomap.eea.europa.eu/arcgis/rest/services/Corine/CLC2018_WM/MapServer/identify"
    TCD_IDENTIFY_URL = "https://image.discomap.eea.europa.eu/arcgis/rest/services/GioLandPublic/HRL_TreeCoverDensity_2018/ImageServer/identify"
    HWSD_METADATA_URL = "https://www.fao.org/land-water/resources/tools/databases/hwsd/en"
    ESDAC_METADATA_URL = "https://esdac.jrc.ec.europa.eu/content/title-russia-soil-map-ukraine"
    SOURCE_KEYS = ("id", "name", "product", "version", "status", "qc", "note", "retrieved_at", "observed_at", "content_sha256", "data")

    def __init__(self, cache_dir: Path, *, transport: httpx.BaseTransport | None = None,
                 timeout_seconds: float = 12.0, cache_max_entries: int = 32) -> None:
        if timeout_seconds <= 0 or cache_max_entries < 1:
            raise ValueError("timeout_seconds must be positive and cache_max_entries at least one")
        self.cache_dir = Path(cache_dir)
        self.raw_dir = self.cache_dir / "raw"
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.cache_max_entries = cache_max_entries
        self._read_cached = lru_cache(maxsize=cache_max_entries)(self._read)

    def read(self, latitude: float, longitude: float, assessment_date: str) -> dict[str, Any]:
        lat = self._coordinate(latitude, "latitude", -90, 90)
        lon = self._coordinate(longitude, "longitude", -180, 180)
        selected = self._date(assessment_date)
        return deepcopy(self._read_cached(lat, lon, selected, int(time.monotonic() // 300)))

    def _read(self, latitude: float, longitude: float, selected: date, _cache_window: int) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        corine, corine_source = self._corine(latitude, longitude, now)
        tcd, tcd_source = self._tree_cover_density(latitude, longitude, now)
        hwsd, hwsd_source = self._hwsd(now)
        esdac, esdac_source = self._esdac(now)
        return {"context": {
            "corine_land_cover": corine,
            "tree_cover_density": tcd,
            "hwsd_v2": hwsd,
            "esdac_ukraine_soil_map": esdac,
            "assessment_date": selected.isoformat(),
        }, "sources": [hwsd_source, esdac_source, corine_source, tcd_source]}

    def _corine(self, latitude: float, longitude: float, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            raw = self._request(self.CLC_IDENTIFY_URL, self._map_params(latitude, longitude, layers="all:1"))
            payload = json.loads(raw)
            results = payload.get("results")
            if not isinstance(results, list) or not results:
                return self._corine_empty(now, self._evidence("corine-land-cover", raw), "Точка поза покриттям CORINE або сервіс не повернув клас.")
            attributes = results[0].get("attributes") if isinstance(results[0], dict) else None
            if not isinstance(attributes, dict):
                return self._corine_empty(now, self._evidence("corine-land-cover", raw), "CORINE identify не містить атрибутів пікселя.")
            code = self._integer(attributes.get("Raster.CODE_18") or attributes.get("Code_18"))
            label = attributes.get("Raster.LABEL3") or attributes.get("LABEL3")
            digest = self._evidence("corine-land-cover", raw)
            if code is None:
                return self._corine_empty(now, digest, "CORINE повернув NoData; числовий клас відсутній.")
            context = {"class_code": code, "class_label": str(label) if label is not None else None,
                       "reference_year": 2018, "resolution_m": 100, "nodata": None,
                       "note": "Статичний контекст земного покриву; не спостереження дороги."}
            source = self._source("corine-land-cover", "Copernicus Land Monitoring Service", "CORINE Land Cover", "2018", "available", "available", None, now, None, digest, {"extraction": "ArcGIS MapServer identify", "class_code": code, "class_label": context["class_label"], "resolution_m": 100, "reference_year": 2018, "nodata": None})
            return context, source
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._corine_empty(now, None, f"CORINE identify недоступний: {self._error(exc)}")

    def _corine_empty(self, now: str, digest: str | None, note: str) -> tuple[dict[str, Any], dict[str, Any]]:
        context = {"class_code": None, "class_label": None, "reference_year": 2018, "resolution_m": 100, "nodata": None, "note": "Числовий клас не отримано; синтетичної заміни немає."}
        source = self._source("corine-land-cover", "Copernicus Land Monitoring Service", "CORINE Land Cover", "2018", "unavailable", "unavailable", note, now, None, digest, {"extraction": "ArcGIS MapServer identify", "class_code": None, "reference_year": 2018, "resolution_m": 100})
        return context, source

    def _tree_cover_density(self, latitude: float, longitude: float, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            raw = self._request(self.TCD_IDENTIFY_URL, {"geometry": json.dumps({"x":longitude,"y":latitude,"spatialReference":{"wkid":4326}},separators=(',',':')), "geometryType": "esriGeometryPoint", "returnGeometry": "false", "returnCatalogItems": "false", "f": "json"})
            payload = json.loads(raw)
            value = payload.get("value")
            density = self._integer(value)
            digest = self._evidence("clms-tree-cover-density", raw)
            if density is None or not 0 <= density <= 100:
                detail = "NoData" if value == "NoData" else "поза покриттям або identify не повернув відсоток"
                return self._tcd_empty(now, digest, f"TCD {detail}; 255/NoData не означає відсутність дерев.")
            context = {"percent": density, "unit": "%", "reference_year": 2018, "resolution_m": 10, "nodata": 255, "note": "Статичний canopy-контекст; не поточне спостереження."}
            source = self._source("clms-tree-cover-density", "Copernicus Land Monitoring Service", "High Resolution Layer Tree Cover Density", "2018", "available", "available", None, now, None, digest, {"extraction": "ArcGIS ImageServer identify", "percent": density, "unit": "%", "reference_year": 2018, "resolution_m": 10, "nodata": 255})
            return context, source
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._tcd_empty(now, None, f"TCD identify недоступний: {self._error(exc)}")

    def _tcd_empty(self, now: str, digest: str | None, note: str) -> tuple[dict[str, Any], dict[str, Any]]:
        context = {"percent": None, "unit": "%", "reference_year": 2018, "resolution_m": 10, "nodata": 255, "note": "Числовий canopy-відсоток не отримано; NoData не є нулем."}
        source = self._source("clms-tree-cover-density", "Copernicus Land Monitoring Service", "High Resolution Layer Tree Cover Density", "2018", "unavailable", "unavailable", note, now, None, digest, {"extraction": "ArcGIS ImageServer identify", "percent": None, "unit": "%", "reference_year": 2018, "resolution_m": 10, "nodata": 255})
        return context, source

    def _hwsd(self, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
        context = {"map_unit_id": None, "attributes": None, "resolution": "30 arc-second (~1 km)", "note": "HWSD v2.0 описує map-unit raster та attribute database; точковий map-unit не читався."}
        try:
            raw = self._request(self.HWSD_METADATA_URL)
            text = raw.decode("utf-8", errors="replace")
            digest = self._evidence("hwsd-v2", raw)
            verified = "HWSD v2.0" in text and "raster" in text.lower() and "attribute" in text.lower()
            note = "Перевірено офіційну metadata-сторінку; bounded point map-unit/attribute read не доступний через цей endpoint. Комерційні права файлів датасету потребують окремого clearance." if verified else "Офіційна metadata-відповідь не підтвердила очікувану семантику HWSD."
            return context, self._source("hwsd-v2", "FAO / IIASA", "Harmonized World Soil Database", "v2.0", "partial", "partial", note, now, None, digest, {"extraction": "official metadata read only", "map_unit_id": None, "attribute_read": False, "resolution": "30 arc-second (~1 km)", "commercial_reuse": "not established"})
        except httpx.HTTPError as exc:
            return context, self._source("hwsd-v2", "FAO / IIASA", "Harmonized World Soil Database", "v2.0", "unavailable", "unavailable", f"HWSD metadata недоступна: {self._error(exc)}; комерційні права файлів датасету не встановлені.", now, None, None, {"extraction": "none", "map_unit_id": None, "attribute_read": False, "commercial_reuse": "not established"})

    def _esdac(self, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
        context = {"reference_year": 1977, "country": "Ukraine", "authors": "Voronina, A.V.; et al.", "scan_available": False, "point_soil_class": None, "note": "Історичний скан не є геоприв'язаним point soil class."}
        try:
            raw = self._request(self.ESDAC_METADATA_URL)
            text = raw.decode("utf-8", errors="replace")
            digest = self._evidence("esdac-ukraine-soil-map", raw)
            title_ok = "Soil Map of Ukraine" in text
            scan_ok = bool(re.search(r'/images/Eudasm/UA/[^"\']+\.(?:jpg|jpeg|png)', text, re.I))
            context["scan_available"] = scan_ok
            note = "Отримано опис ESDAC і посилання на історичний скан карти України (1977, Voronina et al.); без геоприв'язки та легенди клас ґрунту в точці не заявляється." if title_ok and scan_ok else "Опис ESDAC не підтвердив очікуваного посилання на скан; клас ґрунту в точці не заявляється."
            return context, self._source("esdac-ukraine-soil-map", "European Commission JRC", "Soil Map of Ukraine", "1977", "partial", "partial", note, now, None, digest, {"extraction": "official metadata/scan reference", "scan_available": scan_ok, "point_soil_class": None, "georeferenced": False, "reuse_rights": "not established"})
        except httpx.HTTPError as exc:
            return context, self._source("esdac-ukraine-soil-map", "European Commission JRC", "Soil Map of Ukraine", "1977", "unavailable", "unavailable", f"Опис ESDAC недоступний: {self._error(exc)}; клас ґрунту в точці не заявляється.", now, None, None, {"extraction": "none", "scan_available": False, "point_soil_class": None, "georeferenced": False, "reuse_rights": "not established"})

    def _request(self, url: str, params: dict[str, str] | None = None) -> bytes:
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(url, params=params, headers={"Accept": "application/json, text/html;q=0.9"})
        response.raise_for_status()
        return response.content

    @staticmethod
    def _map_params(latitude: float, longitude: float, *, layers: str) -> dict[str, str]:
        return {"geometry": f"{ContextSources._number(longitude)},{ContextSources._number(latitude)}", "geometryType": "esriGeometryPoint", "sr": "4326", "layers": layers, "tolerance": "1", "mapExtent": f"{ContextSources._number(longitude - .01)},{ContextSources._number(latitude - .01)},{ContextSources._number(longitude + .01)},{ContextSources._number(latitude + .01)}", "imageDisplay": "100,100,96", "returnGeometry": "false", "f": "json"}

    def _evidence(self, provider: str, raw: bytes) -> str:
        digest = hashlib.sha256(raw).hexdigest()
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        target = self.raw_dir / f"{digest}.bin"
        if not target.exists():
            temporary = target.with_name(f".{target.name}.{time.time_ns()}.tmp")
            try:
                temporary.write_bytes(raw)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        for path in sorted(self.raw_dir.glob("*.bin"), key=lambda item: item.stat().st_mtime, reverse=True)[self.cache_max_entries:]:
            path.unlink(missing_ok=True)
        return f"sha256:{digest}"

    @classmethod
    def _source(cls, identifier: str, name: str, product: str, version: str | None, status: str, qc: str, note: str | None, retrieved_at: str, observed_at: str | None, digest: str | None, data: dict[str, Any]) -> dict[str, Any]:
        result = {"id": identifier, "name": name, "product": product, "version": version, "status": status, "qc": qc, "note": note, "retrieved_at": retrieved_at, "observed_at": observed_at, "content_sha256": digest, "data": data}
        assert tuple(result) == cls.SOURCE_KEYS
        return result

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            parsed = int(str(value))
        except (TypeError, ValueError):
            return None
        return parsed if str(parsed) == str(value).strip() else None

    @staticmethod
    def _coordinate(value: Any, name: str, lower: float, upper: float) -> float:
        if type(value) not in (int, float) or not math.isfinite(float(value)) or not lower <= float(value) <= upper:
            raise ValueError(f"{name} must be a finite number in range")
        return float(value)

    @staticmethod
    def _date(value: str) -> date:
        if not isinstance(value, str):
            raise ValueError("assessment_date must be YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("assessment_date must be YYYY-MM-DD") from exc

    @staticmethod
    def _number(value: float) -> str:
        return format(value, ".8f").rstrip("0").rstrip(".")

    @staticmethod
    def _error(exc: BaseException) -> str:
        return type(exc).__name__
