"""Bounded point sampling from fixed public static geospatial products.

The adapter deliberately reports natural-soil and DSM context only.  It never
infers road material, passability, or missing pixels from neighbouring data.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


class StaticSources:
    """Read one bounded point window from approved SoilGrids, DEM and land-cover URLs."""

    SOIL_BASE = "https://files.isric.org/soilgrids/latest/data"
    DEM_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
    WORLDCOVER_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
    SOIL_PROPERTIES = ("sand", "silt", "clay")
    SOIL_DEPTH = "0-5cm"
    SOIL_UNIT_REFERENCE = "https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html"
    # Presentation consistency threshold, not a scientific/field acceptance limit.
    TEXTURE_CLOSURE_TOLERANCE_PERCENT_POINTS = 1.0
    WORLD_COVER_LABELS = {
        10: "tree_cover", 20: "shrubland", 30: "grassland", 40: "cropland",
        50: "built_up", 60: "bare_sparse_vegetation", 70: "snow_ice",
        80: "permanent_water", 90: "herbaceous_wetland", 95: "mangroves",
        100: "moss_lichen",
    }

    def __init__(self, cache_dir: Path, *, cache_max_entries: int = 64) -> None:
        if cache_max_entries < 1:
            raise ValueError("cache_max_entries must be positive")
        self.cache_dir = Path(cache_dir)
        self._evidence_dir = self.cache_dir / "evidence"
        self._cache_max_entries = cache_max_entries
        self._read_cached = lru_cache(maxsize=cache_max_entries)(self._read)

    def read(self, latitude: float, longitude: float) -> dict[str, Any]:
        lat = self._coordinate(latitude, "latitude", -90, 90)
        lon = self._coordinate(longitude, "longitude", -180, 180)
        return deepcopy(self._read_cached(lat, lon, int(time.monotonic() // 300)))

    def _read(self, lat: float, lon: float, _cache_window: int) -> dict[str, Any]:
        urls = self._urls_for_point(lat, lon)
        retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        soil, soil_source = self._soil(lat, lon, urls, retrieved_at)
        terrain, terrain_source = self._terrain(lat, lon, urls.get("terrain"), retrieved_at)
        land_cover, cover_source = self._land_cover(lat, lon, urls.get("worldcover"), retrieved_at)
        return {
            "soil": soil,
            "terrain": terrain,
            "land_cover": land_cover,
            "sources": [soil_source, terrain_source, cover_source],
        }

    def _urls_for_point(self, latitude: float, longitude: float) -> dict[str, str]:
        """Build URLs only from trusted product templates; callers cannot supply URLs."""
        urls: dict[str, str] = {}
        for prop in self.SOIL_PROPERTIES:
            root = f"{self.SOIL_BASE}/{prop}/{prop}_{self.SOIL_DEPTH}"
            urls[prop] = f"{root}_Q0.5.vrt"
            urls[f"{prop}_q05"] = f"{root}_Q0.05.vrt"
            urls[f"{prop}_q95"] = f"{root}_Q0.95.vrt"
        # GLO-30 point-post COG footprints extend half a 1-arcsecond pixel
        # north of the named degree; choose using that actual latitude edge.
        lat_tile = math.floor(latitude - 0.5 / 3600)
        lon_tile = math.floor(longitude)
        lat_code = f"N{lat_tile:02d}" if lat_tile >= 0 else f"S{abs(lat_tile):02d}"
        lon_code = f"E{lon_tile:03d}" if lon_tile >= 0 else f"W{abs(lon_tile):03d}"
        dem_name = f"Copernicus_DSM_COG_10_{lat_code}_00_{lon_code}_00_DEM"
        urls["terrain"] = f"{self.DEM_BASE}/{dem_name}/{dem_name}.tif"
        # North-up WorldCover tiles include their north edge, not south edge.
        wc_lat = (math.ceil(latitude / 3) - 1) * 3
        wc_lon = math.floor(longitude / 3) * 3
        wc_lat_code = f"N{wc_lat:02d}" if wc_lat >= 0 else f"S{abs(wc_lat):02d}"
        wc_lon_code = f"E{wc_lon:03d}" if wc_lon >= 0 else f"W{abs(wc_lon):03d}"
        wc_name = f"ESA_WorldCover_10m_2021_v200_{wc_lat_code}{wc_lon_code}_Map.tif"
        urls["worldcover"] = f"{self.WORLDCOVER_BASE}/{wc_name}"
        return urls

    def _soil(self, latitude: float, longitude: float, urls: dict[str, str], retrieved_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
        rows: dict[str, dict[str, Any] | None] = {}
        failures: list[str] = []
        evidence_parts: list[dict[str, Any]] = []
        for key in ("sand", "sand_q05", "sand_q95", "silt", "silt_q05", "silt_q95", "clay", "clay_q05", "clay_q95"):
            sample, reason = self._sample(urls.get(key), latitude, longitude)
            if sample is not None and sample.get("unit") is None:
                # Publisher's property manifest explicitly defines sand/silt/clay
                # in g/kg. Real VRTs contain empty Mapped_units metadata.
                sample = {**sample, "unit": "g/kg", "unit_source": self.SOIL_UNIT_REFERENCE}
            rows[key] = sample
            if reason is not None:
                failures.append(f"{key}: {reason}")
            if sample is not None:
                evidence_parts.append(sample)
        median = {name: rows[name] for name in self.SOIL_PROPERTIES}
        present = [value for value in median.values() if value is not None and value["value"] is not None]
        composition = {
            name: self._composition_value(median[name]) for name in self.SOIL_PROPERTIES
        }
        total = sum(composition.values()) if all(value is not None for value in composition.values()) else None
        closed = math.isclose(total, 100.0, rel_tol=0, abs_tol=self.TEXTURE_CLOSURE_TOLERANCE_PERCENT_POINTS) if total is not None else None
        closure = {"total_percent": total, "tolerance_percent_points": self.TEXTURE_CLOSURE_TOLERANCE_PERCENT_POINTS,
                   "within_tolerance": closed, "normalized": False,
                   "basis": "Presentation consistency check on independent Q0.5 estimates, not field validation"}
        if closed is False:
            failures.append(f"Сума незалежних оцінок — {total:.1f}%; вони не утворюють замкненого складу 100% (поріг перевірки — 1 в.п.). Значення не нормалізовано; це не помилка читання растра й не польова перевірка.")
        depth = {
            "top_cm": 0, "bottom_cm": 5,
            "estimate_kind": "modelled",
            "texture": "; ".join(f"{label}: {composition[prop]:.1f}%" if composition[prop] is not None else f"{label}: —" for prop, label in (("sand", "пісок"), ("silt", "пил"), ("clay", "глина"))),
            "sand_g_kg": self._soil_value(rows["sand"]),
            "silt_g_kg": self._soil_value(rows["silt"]),
            "clay_g_kg": self._soil_value(rows["clay"]),
            "sand_uncertainty_90": self._interval(rows["sand_q05"], rows["sand_q95"]),
            "silt_uncertainty_90": self._interval(rows["silt_q05"], rows["silt_q95"]),
            "clay_uncertainty_90": self._interval(rows["clay_q05"], rows["clay_q95"]),
            "metadata": self._soil_metadata(next(iter(present), None)),
            "status": "available" if len(present) == 3 and closed is True else ("partial" if present else "unknown"),
        }
        status = "available" if len(present) == 3 and closed is True and not failures else ("partial" if evidence_parts else "unavailable")
        digest = self._store_evidence("soilgrids", urls, evidence_parts, retrieved_at) if evidence_parts else None
        source = self._source(
            "soilgrids", "ISRIC", "SoilGrids 2.0", status,
            None if not failures else "; ".join(failures), retrieved_at, digest,
            {"native_support_m": 250, "depth_interval_cm": [0, 5], "properties": list(self.SOIL_PROPERTIES), "road_material_observed": False, "texture_closure": closure},
        )
        return {
            "composition": composition,
            "composition_depth_cm": [0, 5],
            "support_m": 250 if present else None,
            "depths": [depth] if present else [],
            "provenance": {"source": "SoilGrids 2.0", "natural_soil_only": True, "content_sha256": digest},
        }, source

    @staticmethod
    def _soil_value(sample: dict[str, Any] | None) -> float | None:
        if sample is None or sample["value"] is None:
            return None
        # SoilGrids texture values are stored as g/kg.  No percentage is
        # substituted for the native unit; presentation can divide by 10 later.
        return float(sample["value"])

    @staticmethod
    def _composition_value(sample: dict[str, Any] | None) -> float | None:
        value = StaticSources._soil_value(sample)
        if value is None:
            return None
        if sample is not None and sample.get("unit") == "g/kg":
            return value / 10.0
        return None

    @staticmethod
    def _soil_metadata(sample: dict[str, Any] | None) -> dict[str, Any]:
        if sample is None:
            return {"unit": None, "scale_factor": None, "nodata": None, "statistic": None}
        return {key: sample.get(key) for key in ("unit", "unit_source", "scale_factor", "offset", "nodata", "statistic", "crs", "dataset_tags")}

    @staticmethod
    def _interval(lower: dict[str, Any] | None, upper: dict[str, Any] | None) -> dict[str, Any] | None:
        if lower is None or upper is None or lower["value"] is None or upper["value"] is None:
            return None
        if lower.get("unit") != upper.get("unit"):
            return None
        return {"lower": float(lower["value"]), "upper": float(upper["value"]), "unit": lower["unit"]}

    def _terrain(self, latitude: float, longitude: float, url: str | None, retrieved_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
        sample, reason = self._sample(url, latitude, longitude)
        digest = self._store_evidence("copernicus-glo-30", {"terrain": url}, [sample], retrieved_at) if sample else None
        source = self._source(
            "copernicus-glo-30", "Copernicus", "Copernicus DEM GLO-30", "available" if sample and sample["value"] is not None else "unavailable",
            reason, retrieved_at, digest,
            {"surface_kind": "DSM", "vertical_unit": "m", "vertical_datum": (sample or {}).get("dataset_tags", {}).get("vertical_datum", "EGM2008")},
        )
        return {
            "elevation_m": None if sample is None else sample["value"],
            "surface_kind": "DSM", "support_m": 30 if sample and sample["value"] is not None else None,
            "vertical_datum": (sample or {}).get("dataset_tags", {}).get("vertical_datum", "EGM2008") if sample else None,
            "note": "DSM includes vegetation and structures; it is not a bare-earth DTM.",
        }, source

    def _land_cover(self, latitude: float, longitude: float, url: str | None, retrieved_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
        sample, reason = self._sample(url, latitude, longitude)
        code = None if sample is None or sample["value"] is None else int(sample["value"])
        digest = self._store_evidence("esa-worldcover", {"worldcover": url}, [sample], retrieved_at) if sample else None
        source = self._source(
            "esa-worldcover", "ESA", "ESA WorldCover 2021 v200", "available" if code is not None else "unavailable", reason,
            retrieved_at, digest, {"resolution_m": 10, "static_reference_year": 2021, "class_code": code},
        )
        return {
            "class": code, "label": self.WORLD_COVER_LABELS.get(code) if code is not None else None,
            "support_m": 10 if code is not None else None, "reference_year": 2021,
            "note": "Static land-cover context, not a current road or land-change observation.",
        }, source

    def _sample(self, url: str | None, latitude: float, longitude: float) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(url, str) or not url:
            return None, "approved URL missing"
        try:
            import rasterio
            from rasterio.warp import transform
            from rasterio.windows import Window
            # GDAL's /vsicurl reader uses HTTP Range requests for COG data.  These
            # settings prohibit directory scans and cap the per-handle curl cache.
            env = {
                "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
                "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.vrt",
                "CPL_VSIL_CURL_CACHE_SIZE": str(2 * 1024 * 1024),
                "GDAL_HTTP_MAX_RETRY": "0",
                "GDAL_HTTP_TIMEOUT": "15",
            }
            with rasterio.Env(**env), rasterio.open(url) as dataset:
                if dataset.crs is None:
                    return None, "raster CRS missing; coordinate transform not inferred"
                xs, ys = transform("EPSG:4326", dataset.crs, [longitude], [latitude])
                row, col = dataset.index(xs[0], ys[0])
                if not (0 <= row < dataset.height and 0 <= col < dataset.width):
                    return None, "point outside raster extent"
                window = Window(col, row, 1, 1)
                raw_value = dataset.read(1, window=window, masked=True)[0, 0]
                tags = dataset.tags()
                nodata = dataset.nodata
                # Preserve non-finite NoData markers as metadata, not JSON numbers.
                if nodata is not None and not math.isfinite(nodata):
                    nodata = str(nodata)
                masked = bool(getattr(raw_value, "mask", False))
                value = None if masked or not math.isfinite(float(raw_value)) else float(raw_value)
                scale = float(dataset.scales[0]) if dataset.scales and dataset.scales[0] not in (None, 1.0) else self._tag_float(tags, "scale_factor", 1.0)
                offset = float(dataset.offsets[0]) if dataset.offsets and dataset.offsets[0] is not None else 0.0
                if not math.isfinite(scale) or not math.isfinite(offset):
                    return None, "raster scale or offset is non-finite"
                # Rasterio/GDAL ordinarily applies no integer scale automatically.
                # Preserve native units and raw values; only explicit driver scale is
                # applied to expose the physical value while retaining the factor.
                if value is not None and dataset.scales and dataset.scales[0] not in (None, 1.0):
                    value *= scale
                if value is not None:
                    value += offset
                if value is not None and not math.isfinite(value):
                    return None, "scaled raster value is non-finite"
                return {
                    "url": url, "value": value, "raw_value": None if value is None else float(raw_value),
                    "unit": (dataset.units[0] if dataset.units else None) or tags.get("units") or tags.get("Mapped_units") or None,
                    "crs": dataset.crs.to_string(),
                    "scale_factor": scale, "offset": offset, "nodata": nodata, "statistic": tags.get("statistic") or tags.get("Quantile") or None,
                    "dataset_tags": tags, "sample": {"row": row, "column": col, "window": {"width": 1, "height": 1}, "requested_wgs84": [longitude, latitude], "raster_coordinates": [xs[0], ys[0]]},
                }, None if value is not None else "raster NoData"
        except Exception as exc:  # provider faults are deliberately provider-local
            return None, f"raster read failed: {type(exc).__name__}: {str(exc)[:160]}"

    @staticmethod
    def _tag_float(tags: dict[str, str], key: str, default: float) -> float:
        try:
            return float(tags.get(key, default))
        except (TypeError, ValueError):
            return default

    def _store_evidence(self, source_id: str, urls: dict[str, str | None], samples: list[dict[str, Any] | None], retrieved_at: str) -> str:
        payload = {"source_id": source_id, "retrieved_at": retrieved_at, "urls": urls, "sample": samples[0] if len(samples) == 1 else samples}
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self._evidence_dir / f"{digest}.json"
        if not path.exists():
            temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
            try:
                temporary.write_bytes(raw)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        self._evict_evidence()
        return f"sha256:{digest}"

    def _evict_evidence(self) -> None:
        try:
            entries = sorted(self._evidence_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        except OSError:
            return
        for path in entries[self._cache_max_entries:]:
            try:
                path.unlink()
            except OSError:
                pass

    @staticmethod
    def _source(source_id: str, name: str, product: str, status: str, note: str | None, retrieved_at: str, digest: str | None, data: dict[str, Any]) -> dict[str, Any]:
        return {"id": source_id, "name": name, "product": product, "status": status, "qc": status if status != "available" else "available", "note": note, "retrieved_at": retrieved_at, "observed_at": None, "content_sha256": digest, "data": data}

    @staticmethod
    def _coordinate(value: Any, field: str, lower: float, upper: float) -> float:
        if type(value) not in (int, float) or not math.isfinite(float(value)) or not lower <= float(value) <= upper:
            raise ValueError(f"{field} must be a finite number in range")
        return float(value)
