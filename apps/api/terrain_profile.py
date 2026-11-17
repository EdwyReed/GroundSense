"""Bounded DSM and WorldCover samples along a stored terrain transect."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
import math
import re
import threading
from time import monotonic
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from apps.api.land_cover_trace import LandCoverTrace
from apps.api.route_planner import RoutePlanner, _payload
from apps.api.static_sources import StaticSources
from apps.api.surface_profile import SurfaceProfile


class TerrainProfile:
    """Read a compact, fixed-source transect profile; construction does no I/O."""

    MAX_SPACING_M = 250.0
    MAX_POINTS = 81
    MAX_TILE_ATTEMPTS = 6
    CACHE_TTL_SECONDS = 300.0
    CACHE_MAX_ENTRIES = 16
    _PLAN_ID = re.compile(r"^[0-9a-f]{32}$")

    def __init__(self, static_sources: StaticSources | None = None, *, surface_profile: SurfaceProfile | Any | None = None, clock: Callable[[], datetime] | None = None, monotonic_clock: Callable[[], float] = monotonic) -> None:
        self._static_sources = static_sources
        self._surface_profile = surface_profile
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic_clock
        self._cache: OrderedDict[tuple[str, str, str, str], tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def validate(self, payload: Any) -> dict[str, str]:
        if not isinstance(payload, dict) or set(payload) != {"plan_id", "route_id"}:
            raise ValueError("Некоректний запит профілю місцевості.")
        plan_id, route_id = payload.get("plan_id"), payload.get("route_id")
        if not isinstance(plan_id, str) or not self._PLAN_ID.fullmatch(plan_id):
            raise ValueError("Некоректний ідентифікатор плану маршруту.")
        if not isinstance(route_id, str) or not route_id or len(route_id) > 40:
            raise ValueError("Некоректний ідентифікатор маршруту.")
        return {"plan_id": plan_id, "route_id": route_id}

    def cached(self, workspace_id: str, plan_id: str, route_id: str, trip_date: str) -> dict[str, Any] | None:
        key = (workspace_id, plan_id, route_id, trip_date)
        with self._lock:
            row = self._cache.get(key)
            if row is None:
                return None
            saved, response = row
            if self._monotonic() - saved > self.CACHE_TTL_SECONDS:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return deepcopy(response)

    def remember(self, workspace_id: str, response: dict[str, Any]) -> None:
        if response.get("status") not in {"available", "partial"}:
            return
        key = (workspace_id, response["plan_id"], response["route_id"], response["trip_date"])
        with self._lock:
            self._cache[key] = (self._monotonic(), deepcopy(response))
            self._cache.move_to_end(key)
            while len(self._cache) > self.CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)

    def read(self, plan: dict[str, Any], selected: dict[str, str], static_sources: StaticSources | None = None) -> dict[str, Any]:
        adapter = static_sources or self._static_sources
        if adapter is None:
            raise ValueError("Статичні джерела профілю недоступні.")
        if plan.get("analysis_kind") not in {"terrain_transect", "terrain_candidate"}:
            raise ValueError("Профіль доступний лише для аналізу місцевості.")
        route = next((row for row in plan.get("routes", []) if row.get("id") == selected["route_id"]), None)
        if route is None:
            raise LookupError
        coordinates = self._coordinates(route.get("geometry"))
        lengths = [RoutePlanner._distance_m(self._point(a), self._point(b)) for a, b in zip(coordinates, coordinates[1:])]
        distance = sum(lengths)
        if not 0 < distance <= 20_000:
            raise ValueError("Некоректна геометрія лінії аналізу.")
        count = min(self.MAX_POINTS, max(2, math.ceil(distance / self.MAX_SPACING_M) + 1))
        spacing = distance / (count - 1)
        points = [{"chainage_m": spacing * index, "point": self._point_at(coordinates, lengths, spacing * index)} for index in range(count)]
        points[-1]["chainage_m"] = distance
        retrieved_at = self._timestamp()
        terrain, terrain_source = self._product(adapter, points, "terrain", retrieved_at)
        trace = LandCoverTrace().read(adapter, coordinates, retrieved_at, [row['point'] for row in points])
        cover = trace.pop('_point_values')
        trace_source = trace["sources"][0]
        # Explicit point pixels share the trace's handles/windows. A point on a
        # cell boundary must not inherit the previous positive-length span.
        cover_source = deepcopy(trace_source)
        cover_source["extraction_scope"] = "transect_samples"
        cover_source["data"] = {**cover_source["data"], "native_sample_scope": "1x1 transect samples", "known_samples": 0, "total_samples": len(points)}
        for index, row in enumerate(points):
            row["elevation_m"] = terrain[index]
            code = cover[index]
            row["land_cover_class"] = code
            row["land_cover_label"] = adapter.WORLD_COVER_LABELS.get(code) if code is not None else None
        cover_source["data"]["known_samples"] = sum(row["land_cover_class"] is not None for row in points)
        surface_summary, surface_source = self._surface_product(points, plan["request"]["trip_date"], retrieved_at)
        sources = [terrain_source, cover_source, surface_source]
        statuses = [source["status"] for source in sources]
        status = "available" if all(value == "available" for value in statuses) else ("partial" if any(value in {"available", "partial"} for value in statuses) else "unavailable")
        return {"plan_id": selected["plan_id"], "route_id": selected["route_id"], "trip_date": plan["request"]["trip_date"], "status": status,
                "synthetic": False, "evidence_scope": "spaced_point_samples", "coverage": "not_continuous", "distance_m": distance,
                "sample_spacing_m": spacing, "points": points, "sources": sources, "land_cover_trace": trace, "surface_observation_profile": surface_summary,
                "warnings_uk": ["Це рознесені вибірки, а не безперервне покриття; між ними можуть бути перешкоди.",
                                "DSM включає дерева та будівлі; це не модель голого рельєфу.",
                                "Статичне покриття WorldCover 2021 не встановлює поточне затоплення.",
                                "Модель прохідності, несучої здатності ґрунту та рекомендації для транспорту не розраховано."]}

    def _surface_product(self, points: list[dict[str, Any]], trip_date: str, retrieved_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._surface_profile is not None:
            try:
                requested = [{"chainage_m": row["chainage_m"], "point": deepcopy(row["point"])} for row in points]
                return self._surface_profile.read_points(requested, trip_date)
            except Exception:
                pass
        samples = [{"chainage_m": row["chainage_m"], "requested_point": deepcopy(row["point"]), "scl_class": None, "condition": "unknown", "status": "unavailable"} for row in points]
        summary = {"status": "unavailable", "basis": "sentinel2_l2a_scl_profile_points", "coverage": "discrete_points", "assessment_date": trip_date, "retrieved_at": retrieved_at, "observed_at": None, "scene_id": None, "scene_age_days": None, "resolution_m": None, "source_content_sha256": None, "selection_scope": "bounded_catalogue_result", "samples": samples}
        source = {"id": "sentinel-2-l2a", "name": "Sentinel-2", "product": "Sentinel-2 L2A Scene Classification", "version": "L2A", "extraction_scope": "spaced_scene_classification_points", "status": "unavailable", "qc": "unavailable", "note": "Scene Classification source unavailable; no surface condition or mobility inference.", "retrieved_at": retrieved_at, "observed_at": None, "content_sha256": None, "data": {"extraction_scope": "spaced_scene_classification_points", "assessment_date": trip_date, "scene_id": None, "samples": deepcopy(samples)}}
        return summary, source

    def _product(self, adapter: StaticSources, points: list[dict[str, Any]], product: str, retrieved_at: str) -> tuple[list[float | int | None], dict[str, Any]]:
        url_key = "terrain" if product == "terrain" else "worldcover"
        grouped: OrderedDict[str, list[int]] = OrderedDict()
        for index, row in enumerate(points):
            point = row["point"]
            try:
                url = adapter._urls_for_point(point["latitude"], point["longitude"]).get(url_key)
            except Exception:
                url = None
            if isinstance(url, str) and url:
                grouped.setdefault(url, []).append(index)
        values: list[float | int | None] = [None] * len(points)
        samples: list[dict[str, Any]] = []
        failures: list[str] = []
        for url, indexes in list(grouped.items())[:self.MAX_TILE_ATTEMPTS]:
            result, evidence, reason = self._read_tile(url, [points[index]["point"] for index in indexes], product)
            samples.extend(evidence)
            if reason:
                failures.append(reason)
            for position, value in zip(indexes, result):
                values[position] = value
        if len(grouped) > self.MAX_TILE_ATTEMPTS:
            failures.append("перевищено обмеження плиток")
        source_id = "copernicus-glo-30" if product == "terrain" else "esa-worldcover"
        present = sum(value is not None for value in values)
        digest = adapter._store_evidence(source_id, {url_key: list(grouped)[:self.MAX_TILE_ATTEMPTS]}, samples, retrieved_at) if samples else None
        crs_values = sorted({sample.get("crs") for sample in samples if isinstance(sample.get("crs"), str)})
        native_crs: str | list[str] | None = crs_values[0] if len(crs_values) == 1 else (crs_values or None)
        data = ({"surface_kind": "DSM", "vertical_unit": "m", "support_m": 30, "native_crs": native_crs, "native_sample_scope": "1x1 transect samples"} if product == "terrain" else
                {"resolution_m": 10, "static_reference_year": 2021, "native_crs": native_crs, "native_sample_scope": "1x1 transect samples"})
        status = "available" if present == len(values) and not failures else ("partial" if present else "unavailable")
        source = adapter._source(source_id, "Copernicus" if product == "terrain" else "ESA", "Copernicus DEM GLO-30" if product == "terrain" else "ESA WorldCover 2021 v200", status,
                                 None if not failures else "Деякі плитки профілю тимчасово недоступні.", retrieved_at, digest,
                                 {**data, "extraction_scope": "transect_samples", "known_samples": present, "total_samples": len(values)})
        source["extraction_scope"] = "transect_samples"
        return values, source

    @staticmethod
    def _read_tile(url: str, points: list[dict[str, float]], product: str) -> tuple[list[float | int | None], list[dict[str, Any]], str | None]:
        try:
            import rasterio
            from rasterio.warp import transform
            from rasterio.windows import Window
            env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.vrt", "CPL_VSIL_CURL_CACHE_SIZE": str(2 * 1024 * 1024), "GDAL_HTTP_MAX_RETRY": "0", "GDAL_HTTP_TIMEOUT": "15"}
            values, evidence = [], []
            with rasterio.Env(**env), rasterio.open(url) as dataset:
                if dataset.crs is None:
                    return [None] * len(points), evidence, "raster CRS missing"
                xs, ys = transform("EPSG:4326", dataset.crs, [point["longitude"] for point in points], [point["latitude"] for point in points])
                scale = float(dataset.scales[0]) if dataset.scales and dataset.scales[0] not in (None, 1.0) else 1.0
                offset = float(dataset.offsets[0]) if dataset.offsets and dataset.offsets[0] is not None else 0.0
                if not math.isfinite(scale) or not math.isfinite(offset):
                    return [None] * len(points), evidence, "raster scale or offset invalid"
                for point, x, y in zip(points, xs, ys):
                    row, col = dataset.index(x, y)
                    value: float | int | None = None
                    if 0 <= row < dataset.height and 0 <= col < dataset.width:
                        raw = dataset.read(1, window=Window(col, row, 1, 1), masked=True)[0, 0]
                        if not bool(getattr(raw, "mask", False)) and math.isfinite(float(raw)):
                            scaled = float(raw) * scale + offset
                            if math.isfinite(scaled):
                                value = scaled if product == "terrain" else (int(scaled) if scaled.is_integer() and int(scaled) in StaticSources.WORLD_COVER_LABELS else None)
                        raw_evidence = None if bool(getattr(raw, "mask", False)) else (float(raw) if math.isfinite(float(raw)) else str(float(raw)))
                        evidence.append({"url": url, "value": value, "raw_value": raw_evidence, "crs": dataset.crs.to_string(), "scale_factor": scale, "offset": offset,
                                         "sample": {"row": row, "column": col, "window": {"width": 1, "height": 1}, "requested_wgs84": [point["longitude"], point["latitude"]], "raster_coordinates": [x, y]}})
                    else:
                        evidence.append({"url": url, "value": None, "sample": {"requested_wgs84": [point["longitude"], point["latitude"]], "raster_coordinates": [x, y]}})
                    values.append(value)
            return values, evidence, None
        except Exception:
            return [None] * len(points), [], "raster read failed"

    @staticmethod
    def _coordinates(geometry: Any) -> list[list[float]]:
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString" or not isinstance(geometry.get("coordinates"), list) or len(geometry["coordinates"]) < 2:
            raise ValueError("Некоректна геометрія лінії аналізу.")
        output = []
        for raw in geometry["coordinates"]:
            if not isinstance(raw, list) or len(raw) < 2 or type(raw[0]) not in (int, float) or type(raw[1]) not in (int, float) or not math.isfinite(raw[0]) or not math.isfinite(raw[1]) or not -180 <= raw[0] <= 180 or not -90 <= raw[1] <= 90:
                raise ValueError("Некоректна геометрія лінії аналізу.")
            output.append([float(raw[0]), float(raw[1])])
        return output

    @staticmethod
    def _point(coordinate: list[float]) -> dict[str, float]:
        return {"longitude": coordinate[0], "latitude": coordinate[1]}

    def _point_at(self, coordinates: list[list[float]], lengths: list[float], chainage: float) -> dict[str, float]:
        seen = 0.0
        for index, length in enumerate(lengths):
            if chainage <= seen + length or index == len(lengths) - 1:
                ratio = 0.0 if length == 0 else (chainage - seen) / length
                return {"longitude": coordinates[index][0] + (coordinates[index + 1][0] - coordinates[index][0]) * ratio,
                        "latitude": coordinates[index][1] + (coordinates[index + 1][1] - coordinates[index][1]) * ratio}
            seen += length
        return self._point(coordinates[-1])


    def _timestamp(self) -> str:
        return self._clock().replace(tzinfo=UTC).astimezone(UTC).isoformat().replace("+00:00", "Z")


def register_terrain_profile_endpoints(app: FastAPI, mutate: Callable[..., Any], consume_source_budget: Callable[[str], None], *, profile: TerrainProfile | None = None) -> None:
    if profile is not None:
        adapter = profile
    elif getattr(app.state, "data_dir", None) is not None:
        adapter = TerrainProfile(surface_profile=SurfaceProfile(Path(app.state.data_dir) / "surface-profile"))
    else:
        adapter = TerrainProfile()
    app.state.terrain_profile = adapter

    @app.post("/api/v1/terrain-profile")
    async def terrain_profile(request: Request, session: Any = Depends(mutate)) -> dict[str, Any]:
        payload = await _payload(request, RoutePlanner.MAX_REQUEST_BYTES)
        try:
            selected = adapter.validate(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store = getattr(app.state, "route_plan_store", None)
        plan = None if store is None else store.get(session.workspace_id, selected["plan_id"])
        if plan is None:
            raise HTTPException(status_code=404, detail="План маршруту недоступний або строк дії минув.")
        if plan.get("analysis_kind") not in {"terrain_transect", "terrain_candidate"}:
            raise HTTPException(status_code=422, detail="Профіль доступний лише для аналізу місцевості.")
        if not any(route.get("id") == selected["route_id"] for route in plan.get("routes", [])):
            raise HTTPException(status_code=404, detail="Маршрут у плані недоступний.")
        trip_date = plan.get("request", {}).get("trip_date")
        cached = adapter.cached(session.workspace_id, selected["plan_id"], selected["route_id"], trip_date)
        if cached is not None:
            return cached
        slots = getattr(app.state, "context_slots", None)
        if slots is None or not slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Забагато одночасних запитів контексту. Спробуйте пізніше.")
        try:
            consume_source_budget(session.workspace_id)
            response = await run_in_threadpool(adapter.read, plan, selected, app.state.static_sources)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            slots.release()
        adapter.remember(session.workspace_id, response)
        return deepcopy(response)
