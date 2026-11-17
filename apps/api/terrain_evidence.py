"""Bounded, non-operational terrain evidence at one WGS84 point."""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


class TerrainEvidence:
    """Compose bounded DSM, WorldCover, and Q0.5 natural-soil evidence."""

    def __init__(self, static_sources: Any) -> None:
        # Deliberately retain an already-configured approved-source adapter only;
        # construction performs no provider discovery or network access.
        self._static = static_sources

    def read(self, latitude: float, longitude: float) -> dict[str, Any]:
        lat = self._static._coordinate(latitude, "latitude", -90, 90)
        lon = self._static._coordinate(longitude, "longitude", -180, 180)
        urls = self._static._urls_for_point(lat, lon)
        retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        soil, soil_source = self._soil(lat, lon, urls, retrieved_at)
        terrain, terrain_source = self._terrain(lat, lon, urls.get("terrain"), retrieved_at)
        vegetation, cover_source = self._vegetation(lat, lon, urls.get("worldcover"), retrieved_at)
        return {"ground_composition": soil, "local_terrain": terrain, "vegetation": vegetation,
                "sources": [soil_source, terrain_source, cover_source]}

    def _soil(self, lat: float, lon: float, urls: dict[str, str], retrieved_at: str):
        values: dict[str, float | None] = {name: None for name in self._static.SOIL_PROPERTIES}
        samples: list[dict[str, Any]] = []
        note = None
        for name in self._static.SOIL_PROPERTIES:
            sample, reason = self._static._sample(urls.get(name), lat, lon)
            if sample and sample.get("value") is not None:
                # SoilGrids texture Q0.5 native values are g/kg; conversion is exact.
                values[name] = float(sample["value"]) / 10.0
                samples.append(sample)
            elif reason != "raster NoData":
                note = "soil raster transport/read failure; remaining soil reads skipped"
                break
        total = sum(values.values()) if all(value is not None for value in values.values()) else None
        closure = {"total_percent": total, "normalized": False,
                   "basis": "Independent SoilGrids Q0.5 estimates; values are not normalized."}
        if total is not None and not math.isclose(total, 100.0, abs_tol=1.0):
            note = "independent Q0.5 texture estimates do not close to 100%; values were not normalized"
        status = "available" if all(value is not None for value in values.values()) and note is None else (
            "partial" if samples else "unavailable")
        digest = self._static._store_evidence("soilgrids", {name: urls.get(name) for name in self._static.SOIL_PROPERTIES}, samples, retrieved_at) if samples else None
        source = self._static._source("soilgrids", "ISRIC", "SoilGrids 2.0", status, note, retrieved_at, digest,
            {"depth_interval_cm": [0, 5], "statistic": "Q0.5", "native_unit": "g/kg",
             "percent_conversion": "g/kg divided by 10", "uncertainty": "unknown: Q0.05/Q0.95 not read", "texture_closure": closure})
        return {"status": status, "composition": values, "support_m": 250 if samples else None,
                "composition_depth_cm": [0, 5], "depth_cm": [0, 5], "estimate": "SoilGrids Q0.5 modelled natural soil",
                "unit": "percent", "closure": closure, "uncertainty": "unknown: only Q0.5 requested", "source_id": "soilgrids"}, source

    def _terrain(self, lat: float, lon: float, url: str | None, retrieved_at: str):
        sample, reason = self._window(url, lat, lon, 1)
        slope = None
        footprint = None
        evidence: list[dict[str, Any]] = []
        if sample is not None:
            footprint = sample["footprint"]
            evidence.append(sample["evidence"])
            data = sample["data"]
            if data.shape == (3, 3) and not sample["masked"].any():
                slope = self._slope_degrees(data, sample["dataset"], sample["window"])
            else:
                reason = "DSM edge or NoData in required 3x3 window"
        note = "DSM surface includes vegetation and structures; it is not a bare-earth DTM, so this is not a bare-earth slope."
        if reason:
            note += " Local slope unknown: " + self._safe_reason(reason)
        status = "available" if slope is not None else "unavailable"
        digest = self._static._store_evidence("copernicus-glo-30", {"terrain": url}, evidence, retrieved_at) if evidence else None
        source = self._static._source("copernicus-glo-30", "Copernicus", "Copernicus DEM GLO-30", status, None if slope is not None else self._safe_reason(reason), retrieved_at, digest,
            {"surface_kind": "DSM", "window_pixels": [3, 3], "extraction_footprint": footprint})
        return {"status": status, "slope_deg": slope, "slope_degrees": slope, "surface_kind": "DSM", "window_pixels": [3, 3],
                "extraction_footprint": footprint, "note": note, "source_id": "copernicus-glo-30"}, source

    def _vegetation(self, lat: float, lon: float, url: str | None, retrieved_at: str):
        import numpy as np
        sample, reason = self._window(url, lat, lon, None)
        valid_fraction = tree_percent = footprint = None
        evidence: list[dict[str, Any]] = []
        if sample is not None:
            evidence.append(sample["evidence"])
            footprint = sample["footprint"]
            valid = ~sample["masked"] & np.isin(sample["data"], list(self._static.WORLD_COVER_LABELS))
            sample["evidence"]["classified_pixel_count"] = int(valid.sum())
            valid_fraction = float(valid.mean())
            if valid.any():
                tree_percent = float((sample["data"][valid] == 10).mean() * 100)
            else:
                reason = "WorldCover window has no valid pixels"
        note = ("Landscape tree-cover fraction from static ESA WorldCover 2021, not vehicle access. "
                "canopy density, stems per ha, and clearance are unknown.")
        if reason:
            note += " " + self._safe_reason(reason)
        status = "available" if tree_percent is not None else "unavailable"
        digest = self._static._store_evidence("esa-worldcover", {"worldcover": url}, evidence, retrieved_at) if evidence else None
        source = self._static._source("esa-worldcover", "ESA", "ESA WorldCover 2021 v200", status, None if tree_percent is not None else self._safe_reason(reason), retrieved_at, digest,
            {"reference_year": 2021, "window_max_pixels": [51, 51], "extraction_footprint": footprint})
        return {"status": status, "tree_cover_percent": tree_percent, "tree_cover_percent_of_valid": tree_percent,
                "valid_fraction": valid_fraction, "valid_coverage_fraction": valid_fraction,
                "reference_year": 2021, "window_max_pixels": [51, 51], "footprint_m": None if footprint is None else footprint["physical_size_m"], "extraction_footprint": footprint,
                "canopy_density_percent": None, "stems_per_ha": None, "clearance_m": None,
                "note": note, "source_id": "esa-worldcover"}, source

    def _window(self, url: str | None, lat: float, lon: float, radius: int):
        if not isinstance(url, str) or not url:
            return None, "approved URL missing"
        try:
            import numpy as np
            import rasterio
            from rasterio.windows import Window
            from rasterio.warp import transform
            env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.vrt",
                   "CPL_VSIL_CURL_CACHE_SIZE": str(2 * 1024 * 1024), "GDAL_HTTP_MAX_RETRY": "0", "GDAL_HTTP_TIMEOUT": "15"}
            with rasterio.Env(**env), rasterio.open(url) as dataset:
                if dataset.crs is None:
                    return None, "raster CRS missing"
                xs, ys = transform("EPSG:4326", dataset.crs, [lon], [lat])
                row, col = dataset.index(xs[0], ys[0])
                if not (0 <= row < dataset.height and 0 <= col < dataset.width):
                    return None, "point outside raster extent"
                if radius is None:
                    # Choose per-axis radii for an approximately 250 m (full-size)
                    # neighbourhood, never exceeding 51x51 source pixels.
                    x0, y0 = dataset.transform * (col + 0.5, row + 0.5)
                    xe, ye = dataset.transform * (col + 1.5, row + 0.5)
                    xs_, ys_ = dataset.transform * (col + 0.5, row + 1.5)
                    (lon0, lone), (lat0, late) = transform(dataset.crs, "EPSG:4326", [x0, xe], [y0, ye])
                    (lons, _), (lats, _) = transform(dataset.crs, "EPSG:4326", [xs_, x0], [ys_, y0])
                    radius_x = min(25, max(0, int(125 / self._haversine_m(lat0, lon0, late, lone))))
                    radius_y = min(25, max(0, int(125 / self._haversine_m(lat0, lon0, lats, lons))))
                else:
                    radius_x = radius_y = radius
                requested = Window(col - radius_x, row - radius_y, radius_x * 2 + 1, radius_y * 2 + 1)
                clipped = requested.intersection(Window(0, 0, dataset.width, dataset.height))
                raw = dataset.read(1, window=clipped, masked=True)
                mask = np.ma.getmaskarray(raw) | ~np.isfinite(raw.data)
                bounds = rasterio.windows.bounds(clipped, dataset.transform)
                (west, east), (south, north) = transform(dataset.crs, "EPSG:4326", [bounds[0], bounds[2]], [bounds[1], bounds[3]])
                width_m = self._haversine_m(south, west, south, east)
                height_m = self._haversine_m(south, west, north, west)
                return {"data": raw.data, "masked": mask, "window": clipped, "dataset": dataset,
                        "evidence": {"url": url, "sample": {"row": row, "column": col,
                                      "window": {"column_offset": int(clipped.col_off), "row_offset": int(clipped.row_off),
                                                 "width": int(clipped.width), "height": int(clipped.height)},
                                      "requested_wgs84": [lon, lat]}, "valid_pixel_count": int((~mask).sum())},
                        "footprint": {"requested_wgs84": [lon, lat], "crs": dataset.crs.to_string(),
                                      "window_pixels": [int(clipped.width), int(clipped.height)], "bounds_native": list(bounds),
                                      "requested_window_pixels": [int(requested.width), int(requested.height)],
                                      "physical_size_m": {"width": width_m, "height": height_m}}}, None
        except Exception as exc:
            return None, f"raster read failed: {type(exc).__name__}"

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        lat_delta = math.radians(lat2 - lat1)
        lon_delta = math.radians(lon2 - lon1)
        a = math.sin(lat_delta / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(lon_delta / 2) ** 2
        return 6_371_008.8 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def _slope_degrees(data, dataset, window) -> float:
        from rasterio.transform import xy
        from rasterio.warp import transform
        def distance(row1, col1, row2, col2):
            x1, y1 = xy(dataset.transform, int(window.row_off + row1), int(window.col_off + col1), offset="center")
            x2, y2 = xy(dataset.transform, int(window.row_off + row2), int(window.col_off + col2), offset="center")
            (lon1, lon2), (lat1, lat2) = transform(dataset.crs, "EPSG:4326", [x1, x2], [y1, y2])
            # Haversine metres avoids a new geodesy dependency while still using
            # actual horizontal surface distance rather than raster units.
            lat_delta = math.radians(lat2 - lat1)
            lon_delta = math.radians(lon2 - lon1)
            a = math.sin(lat_delta / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(lon_delta / 2) ** 2
            return 6_371_008.8 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        dx = distance(1, 0, 1, 2); dy = distance(0, 1, 2, 1)
        if dx <= 0 or dy <= 0:
            raise ValueError("invalid physical DSM pixel spacing")
        gradient_x = (float(data[1, 2]) - float(data[1, 0])) / dx
        gradient_y = (float(data[2, 1]) - float(data[0, 1])) / dy
        return math.degrees(math.atan(math.hypot(gradient_x, gradient_y)))

    @staticmethod
    def _safe_reason(reason: str | None) -> str:
        if not reason:
            return "source unavailable"
        return reason if reason in {"approved URL missing", "raster CRS missing", "point outside raster extent", "DSM edge or NoData in required 3x3 window", "WorldCover window has no valid pixels"} else "provider read failed"
