"""Selected-route point-sample context from fixed public data sources."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
import math
import re
import threading
from time import monotonic
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from apps.api.antecedent_precipitation import summarize_antecedent_precipitation
from apps.api.route_planner import RoutePlanner, _payload
from apps.api.terrain_sections import MAX_SECTIONS
from apps.api.soil_type import SoilTypeSource
from apps.api.model_soil_water import summarize_model_soil_water
from apps.api.surface_observation import SurfaceObservation
from apps.api.terrain_evidence import TerrainEvidence
from apps.api.tree_cover_density import TreeCoverDensity
from apps.api.weather_day import summarize_weather_day
from apps.api.weather_outlook import summarize_weather_outlook


class RouteContext:
    """Network-free context assembler; provider work happens only in ``build``."""

    CACHE_TTL_SECONDS = 300.0
    CACHE_MAX_ENTRIES = 16
    PROVIDER_MAX_WORKERS = 4
    TERRAIN_CACHE_TTL_SECONDS = 300.0
    TERRAIN_CACHE_MAX_ENTRIES = 64
    _PLAN_ID = re.compile(r"^[0-9a-f]{32}$")

    def __init__(self, *, clock: Callable[[], datetime] | None = None, monotonic_clock: Callable[[], float] = monotonic, terrain_evidence_factory: Callable[[Any], Any] | None = None, canopy_source: Any = None, surface_observation: Any = None, soil_type_source: Any = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._terrain_evidence_factory = terrain_evidence_factory or TerrainEvidence
        self._canopy_source = canopy_source
        self._surface_observation = surface_observation
        self._soil_type_source = soil_type_source
        self._monotonic = monotonic_clock
        self._cache: OrderedDict[tuple[str, str, str, int, str, float | int | None], tuple[float, dict[str, Any]]] = OrderedDict()
        self._terrain_cache: OrderedDict[tuple[int, float, float], tuple[float, Any, dict[str, Any]]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def validate(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Некоректний запит контексту маршруту.")
        plan_id, route_id, section_index = payload.get("plan_id"), payload.get("route_id"), payload.get("section_index")
        if not isinstance(plan_id, str) or not self._PLAN_ID.fullmatch(plan_id):
            raise ValueError("Некоректний ідентифікатор плану маршруту.")
        if not isinstance(route_id, str) or not route_id or len(route_id) > 40:
            raise ValueError("Некоректний ідентифікатор маршруту.")
        if type(section_index) is not int or not 0 <= section_index < MAX_SECTIONS:
            raise ValueError("Некоректний індекс ділянки маршруту.")
        selected = {"plan_id": plan_id, "route_id": route_id, "section_index": section_index}
        if "sample_chainage_m" in payload:
            chainage = payload["sample_chainage_m"]
            if not isinstance(chainage, (int, float)) or isinstance(chainage, bool) or not 0 <= chainage <= 20_000 or not math.isfinite(chainage):
                raise ValueError("Некоректна відстань вибірки вздовж лінії.")
            selected["sample_chainage_m"] = chainage
        return selected

    def cached(self, workspace_id: str, plan_id: str, route_id: str, section_index: int, trip_date: str, sample_chainage_m: float | int | None = None) -> dict[str, Any] | None:
        key = (workspace_id, plan_id, route_id, section_index, trip_date, sample_chainage_m)
        now = self._monotonic()
        with self._cache_lock:
            row = self._cache.get(key)
            if row is None:
                return None
            saved, value = row
            if now - saved > self.CACHE_TTL_SECONDS:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return deepcopy(value)

    def remember(self, workspace_id: str, response: dict[str, Any]) -> None:
        if response["status"] not in {"available", "partial"}:
            return
        selection = response.get("sample_selection")
        chainage = selection.get("chainage_m") if isinstance(selection, dict) else None
        key = (workspace_id, response["plan_id"], response["route_id"], response["section_index"], response["trip_date"], chainage)
        with self._cache_lock:
            self._cache[key] = (self._monotonic(), deepcopy(response))
            self._cache.move_to_end(key)
            while len(self._cache) > self.CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)

    def build(self, plan: dict[str, Any], selected: dict[str, Any], static_sources: Any, live_weather: Any) -> dict[str, Any]:
        selected, route = self.resolve_selection(plan, selected)
        sections = self._route_sections(route)
        point = selected.get("sample_point", sections[selected["section_index"]]["point"])
        retrieved_at = self._timestamp()
        terrain, terrain_source = self._static_part(static_sources, "terrain", point, retrieved_at)
        land_cover, land_source = self._static_part(static_sources, "land_cover", point, retrieved_at)
        extra = {}
        if plan.get("analysis_kind") in {"terrain_transect", "terrain_candidate"}:
            # Fixed, request-local work: at most four tasks; no detached reads
            # and no persistent executor queue outside the existing two slots.
            with ThreadPoolExecutor(max_workers=self.PROVIDER_MAX_WORKERS, thread_name_prefix="groundsense-section") as pool:
                weather_read = pool.submit(self._weather, live_weather, point, plan["request"]["trip_date"], include_antecedent=True)
                terrain_read = pool.submit(self._terrain_extra, static_sources, point, retrieved_at)
                canopy_read = pool.submit(self._canopy_and_soil, point, retrieved_at)
                surface_read = pool.submit(self._surface, point, plan["request"]["trip_date"], retrieved_at) if self._surface_observation is not None else None
                weather, weather_source = weather_read.result()
                extra = terrain_read.result()
                canopy_pair, soil_pair = canopy_read.result()
                canopy, canopy_source = canopy_pair
                surface = surface_read.result() if surface_read is not None else None
            sources = [land_source, terrain_source, weather_source]
            sources.extend({**source, "extraction_scope": "soil_point" if source["id"] == "soilgrids" else "local_window"} for source in extra.get("sources", []))
            extra["canopy_cover"] = canopy
            sources.append({**canopy_source, "extraction_scope": "canopy_point"})
            if soil_pair is not None:
                soil_type, soil_source = soil_pair
                extra["soil_type"] = soil_type
                sources.append({**soil_source, "extraction_scope": "soil_mapping_unit"})
            if surface is not None:
                surface_observation, surface_source = surface
                extra["surface_observation"] = surface_observation
                sources.append({**surface_source, "extraction_scope": "scene_classification_point"})
        else:
            weather, weather_source = self._weather(live_weather, point, plan["request"]["trip_date"])
            sources = [land_source, terrain_source, weather_source]
        statuses = [source["status"] for source in sources]
        available = sum(status == "available" for status in statuses)
        status = "available" if available == len(statuses) else ("partial" if any(value in {"available", "partial"} for value in statuses) else "unavailable")
        response = {
            "plan_id": selected["plan_id"], "route_id": selected["route_id"], "section_index": selected["section_index"],
            "trip_date": plan["request"]["trip_date"], "status": status, "synthetic": False,
            "sections": sections, "evidence_scope": "point_sample", "coverage": "not_continuous",
            "land_cover": land_cover, "terrain": terrain, "ground_composition": extra.get("ground_composition", {"status": "unknown"}), "weather": weather, "sources": sources,
            **{key: extra[key] for key in ("local_terrain", "vegetation", "canopy_cover", "surface_observation", "soil_type") if key in extra},
            "warnings_uk": [
                "Точкові вибірки не описують безперервне покриття ділянки.",
                "Land Cover 2021 не є поточним спостереженням затоплення.",
                "Вологість погодної сітки не є несучою здатністю дороги.",
                "Транспорт і відновлення не оцінено.",
            ],
        }
        if "sample_chainage_m" in selected:
            response["sample_selection"] = {"kind": "line_chainage", "chainage_m": selected["sample_chainage_m"], "point": dict(point)}
        return response

    def resolve_selection(self, plan: dict[str, Any], selected: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        route = next((item for item in plan["routes"] if item.get("id") == selected["route_id"]), None)
        if route is None:
            raise LookupError
        if plan.get('analysis_kind') in {'terrain_transect', 'terrain_candidate'}:
            self._validated_transect_geometry(route.get('geometry'))
        sections = self._route_sections(route)
        index = selected['section_index']
        if type(index) is not int or not 0 <= index < len(sections):
            raise ValueError("Некоректний індекс ділянки маршруту.")
        if "sample_chainage_m" not in selected:
            return selected, route
        if plan.get("analysis_kind") not in {"terrain_transect", "terrain_candidate"}:
            raise ValueError("Вибір позиції вздовж лінії доступний лише для аналізу місцевості.")
        coordinates, lengths, total = self._validated_transect_geometry(route.get("geometry"))
        chainage = selected["sample_chainage_m"]
        start, end = sections[index]['from_m'], sections[index]['to_m']
        if not start <= chainage <= end:
            raise ValueError("Вибрана відстань не належить вказаній ділянці лінії.")
        return {**selected, "sample_point": self._point_at(coordinates, lengths, chainage)}, route

    def _validated_transect_geometry(self, geometry: Any) -> tuple[list[list[float]], list[float], float]:
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise ValueError("Некоректна геометрія лінії аналізу.")
        raw_coordinates = geometry.get("coordinates")
        if not isinstance(raw_coordinates, list) or not 2 <= len(raw_coordinates) <= 256:
            raise ValueError("Некоректна геометрія лінії аналізу.")
        coordinates: list[list[float]] = []
        for coordinate in raw_coordinates:
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                raise ValueError("Некоректна геометрія лінії аналізу.")
            longitude, latitude = coordinate
            if (not isinstance(longitude, (int, float)) or isinstance(longitude, bool) or not isinstance(latitude, (int, float))
                    or isinstance(latitude, bool) or not -180 <= longitude <= 180 or not -90 <= latitude <= 90
                    or not math.isfinite(longitude) or not math.isfinite(latitude)):
                raise ValueError("Некоректна геометрія лінії аналізу.")
            coordinates.append([float(longitude), float(latitude)])
        lengths = [self._distance(coordinates[index], coordinates[index + 1]) for index in range(len(coordinates) - 1)]
        total = sum(lengths)
        if not math.isfinite(total) or not 0 < total <= 20_000:
            raise ValueError("Некоректна геометрія лінії аналізу.")
        return coordinates, lengths, total

    def _terrain_extra(self, static_sources: Any, point: dict[str, float], retrieved_at: str) -> dict[str, Any]:
        key = (id(static_sources), point["latitude"], point["longitude"])
        now = self._monotonic()
        with self._cache_lock:
            row = self._terrain_cache.get(key)
            if row is not None:
                saved, owner, value = row
                if owner is static_sources and now - saved <= self.TERRAIN_CACHE_TTL_SECONDS:
                    self._terrain_cache.move_to_end(key)
                    cached = deepcopy(value)
                    for source in cached["sources"]:
                        source["cached"] = True
                    return cached
                self._terrain_cache.pop(key, None)
        try:
            value = self._terrain_evidence_factory(static_sources).read(point["latitude"], point["longitude"])
        except Exception:
            return {"ground_composition": {"status": "unavailable"}, "local_terrain": {"slope_deg": None},
                    "vegetation": {"tree_cover_percent": None, "valid_fraction": None},
                    "sources": [{"id": "terrain-evidence", "status": "unavailable", "retrieved_at": retrieved_at,
                                 "note": "Розширені дані місцевості тимчасово недоступні."}]}
        sources = value.get("sources", [])
        composition = value.get("ground_composition", {}).get("composition", {})
        # Reuse actual static reads, not a failure/unknown that should be retried.
        if sources and all(source.get("status") in {"available", "partial"} for source in sources) and all(
            type(composition.get(name)) in (int, float) and math.isfinite(composition[name]) and 0 <= composition[name] <= 100
            for name in ("sand", "silt", "clay")
        ):
            with self._cache_lock:
                self._terrain_cache[key] = (now, static_sources, deepcopy(value))
                self._terrain_cache.move_to_end(key)
                while len(self._terrain_cache) > self.TERRAIN_CACHE_MAX_ENTRIES:
                    self._terrain_cache.popitem(last=False)
        return value

    def _canopy_and_soil(self, point: dict[str, float], retrieved_at: str) -> tuple[Any, Any]:
        # Sequential reads share one of the existing four joined worker lanes.
        canopy = self._canopy(point, retrieved_at)
        if self._soil_type_source is None:
            return canopy, None
        try:
            soil = self._soil_type_source.read_point(point["latitude"], point["longitude"])
        except Exception:
            soil = ({"status": "unavailable", "basis": "hwsd_v2_smu_dominant_soil", "requested_point": dict(point),
                     "map_unit_id": None, "wrb_code": None, "wrb_name": None, "share_percent": None,
                     "resolution_arc_seconds": None, "temporal_scope": "static_reference",
                     "classification_system": "WRB 2022", "spatial_scope": "soil_mapping_unit"},
                    {"id": "hwsd-v2", "product": "Harmonized World Soil Database v2.0", "status": "unavailable",
                     "qc": "unavailable", "retrieved_at": retrieved_at, "observed_at": None, "content_sha256": None,
                     "note": "Довідковий тип ґрунту не отримано.", "data": {"commercial_reuse": "not_established"}})
        return canopy, soil

    def _canopy(self, point: dict[str, float], retrieved_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            canopy, source = self._canopy_source.read_point(point["latitude"], point["longitude"])
        except Exception:
            canopy = {"percent": None, "reference_year": 2018, "resolution_m": 10}
            source = {"id": "clms-tree-cover-density", "status": "unavailable", "retrieved_at": retrieved_at}
        if source["status"] != "available":
            source = {**source, "note": "Зімкнутість крон не отримано; це не нульовий покрив."}
        return canopy, source

    def _surface(self, point: dict[str, float], trip_date: str, retrieved_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            return self._surface_observation.read_point(point["latitude"], point["longitude"], trip_date)
        except Exception:
            return ({"status": "unavailable", "basis": "sentinel2_l2a_scl_point", "condition": "unknown"},
                    {"id": "sentinel-2-l2a", "status": "unavailable", "qc": "unavailable", "retrieved_at": retrieved_at, "data": {}})

    def _static_part(self, adapter: Any, kind: str, point: dict[str, float], retrieved_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
        source_id = "copernicus-glo-30" if kind == "terrain" else "esa-worldcover"
        try:
            urls = adapter._urls_for_point(point["latitude"], point["longitude"])
            if kind == "terrain":
                return adapter._terrain(point["latitude"], point["longitude"], urls.get("terrain"), retrieved_at)
            return adapter._land_cover(point["latitude"], point["longitude"], urls.get("worldcover"), retrieved_at)
        except Exception:
            value = ({"elevation_m": None, "surface_kind": "DSM", "support_m": None, "vertical_datum": None} if kind == "terrain"
                     else {"class": None, "label": None, "support_m": None, "reference_year": 2021})
            return value, {"id": source_id, "status": "unavailable", "qc": "unavailable", "note": "Джерело контексту тимчасово недоступне.", "retrieved_at": retrieved_at, "data": {"static_reference_year": 2021} if kind == "land_cover" else {}}

    def _weather(self, adapter: Any, point: dict[str, float], trip_date: str, *, include_antecedent: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            forecast = getattr(adapter, "forecast_for_section", adapter.forecast) if include_antecedent else adapter.forecast
            dto = forecast(point["latitude"], point["longitude"], trip_date)
            source = self._safe_weather_source(dto.get("source"))
            weather = {key: deepcopy(dto.get(key)) for key in ("assessment_date", "requested_point", "grid_point", "units", "series", "qc") if key in dto}
            weather['day_summary'] = summarize_weather_day(dto, trip_date)
            if include_antecedent and 'antecedent_series' in dto:
                weather['antecedent_precipitation'] = summarize_antecedent_precipitation(dto, trip_date)
            if include_antecedent:
                weather['soil_water'] = summarize_model_soil_water(dto, trip_date)
                weather['outlook'] = summarize_weather_outlook(dto, trip_date)
            weather["source"] = deepcopy(source)
            weather["status"] = dto.get("qc", {}).get("status", "available")
            source["status"] = weather["status"]
            source["qc"] = weather["status"]
            weather["source"] = deepcopy(source)
            return weather, source
        except Exception as exc:
            if getattr(exc, "status_code", None) == 422:
                return {"status": "date_out_of_range"}, {"id": "open-meteo-icon-global", "status": "unavailable", "qc": "unavailable", "note": "Обрана дата поза доступним горизонтом моделі.", "data": {}}
            return {"status": "unavailable"}, {"id": "open-meteo-icon-global", "status": "unavailable", "qc": "unavailable", "note": "Погодне джерело тимчасово недоступне.", "data": {}}

    @staticmethod
    def _safe_weather_source(source: Any) -> dict[str, Any]:
        source = source if isinstance(source, dict) else {}
        return {key: deepcopy(source[key]) for key in ("id", "provider", "product", "model", "retrieved_at", "issue_time", "license", "service_usage", "attribution_url", "content_sha256", "cached") if key in source}

    def _route_sections(self, route: dict[str, Any]) -> list[dict[str, Any]]:
        spans = route.get('section_spans')
        if route.get('geometry_kind') == 'terrain_candidate' and spans is None:
            # Old persisted candidates have no terrain-segmentation evidence.
            # Keep them inspectable as one explicitly unknown span, not thirds.
            _, _, total = self._validated_transect_geometry(route['geometry'])
            spans = [{'from_m': 0.0, 'to_m': total, 'label_uk': 'Поділ за місцевістю недоступний', 'basis': 'unknown'}]
        return self._sections(route['geometry'], spans)

    def _sections(self, geometry: Any, spans: Any = None) -> list[dict[str, Any]]:
        coordinates = geometry["coordinates"]
        lengths = [self._distance(coordinates[index], coordinates[index + 1]) for index in range(len(coordinates) - 1)]
        total = sum(lengths)
        if total <= 0:
            raise ValueError("Некоректна геометрія маршруту.")
        if spans is None:
            # Preserve historical road/transect handles; new off-road candidates
            # carry immutable evidence-derived spans in the owned route plan.
            spans = [{'from_m': total * index / 3, 'to_m': total * (index + 1) / 3} for index in range(3)]
        if not isinstance(spans, list) or not 1 <= len(spans) <= MAX_SECTIONS:
            raise ValueError('Некоректний поділ маршруту.')
        sections = []
        previous = 0.0
        for index, span in enumerate(spans):
            if not isinstance(span, dict):
                raise ValueError('Некоректний поділ маршруту.')
            start, end = span.get('from_m'), span.get('to_m')
            if (not isinstance(start, (int, float)) or isinstance(start, bool) or not isinstance(end, (int, float)) or isinstance(end, bool)
                    or not math.isfinite(start) or not math.isfinite(end)
                    or abs(start - previous) > 1e-6 or not start < end <= total + 1e-6):
                raise ValueError('Некоректний поділ маршруту.')
            sections.append({**deepcopy(span), "index": index, "from_m": start, "to_m": end, "point": self._point_at(coordinates, lengths, (start + end) / 2), "geometry": {"type": "LineString", "coordinates": self._slice(coordinates, lengths, start, end)}})
            previous = end
        if abs(previous - total) > 1e-6:
            raise ValueError('Некоректний поділ маршруту.')
        return sections

    def _slice(self, coordinates: list[list[float]], lengths: list[float], start: float, end: float) -> list[list[float]]:
        output = [self._coordinate_at(coordinates, lengths, start)]
        cumulative = 0.0
        for index, length in enumerate(lengths):
            cumulative += length
            if start < cumulative < end:
                output.append([float(coordinates[index + 1][0]), float(coordinates[index + 1][1])])
        output.append(self._coordinate_at(coordinates, lengths, end))
        return output

    def _point_at(self, coordinates: list[list[float]], lengths: list[float], distance: float) -> dict[str, float]:
        longitude, latitude = self._coordinate_at(coordinates, lengths, distance)
        return {"longitude": longitude, "latitude": latitude}

    def _coordinate_at(self, coordinates: list[list[float]], lengths: list[float], distance: float) -> list[float]:
        passed = 0.0
        for index, length in enumerate(lengths):
            if distance <= passed + length or index == len(lengths) - 1:
                portion = 0.0 if length == 0 else (distance - passed) / length
                left, right = coordinates[index], coordinates[index + 1]
                return [float(left[0]) + (float(right[0]) - float(left[0])) * portion, float(left[1]) + (float(right[1]) - float(left[1])) * portion]
            passed += length
        return [float(coordinates[-1][0]), float(coordinates[-1][1])]

    @staticmethod
    def _distance(left: list[float], right: list[float]) -> float:
        lat1, lon1, lat2, lon2 = map(math.radians, (left[1], left[0], right[1], right[0]))
        a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        return 6_371_000 * 2 * math.asin(math.sqrt(a))

    def _timestamp(self) -> str:
        value = self._clock()
        return value.replace(tzinfo=UTC).astimezone(UTC).isoformat().replace("+00:00", "Z")


def register_route_context_endpoints(app: FastAPI, session_for: Callable[..., Any], mutate: Callable[..., Any], consume_source_budget: Callable[[str], None], *, context: RouteContext | None = None) -> None:
    """Register selected-section context after the route-plan endpoint."""
    data_dir = getattr(app.state, "data_dir", None)
    adapter = context or RouteContext(canopy_source=TreeCoverDensity(data_dir / "tree-cover-density") if data_dir is not None else None,
                                      surface_observation=SurfaceObservation(data_dir / "surface-observation") if data_dir is not None else None,
                                      soil_type_source=SoilTypeSource(data_dir / "soil-type", adapter_lookup=lambda: app.state.extra_sources.get("hwsd")) if data_dir is not None else None)
    app.state.route_context = adapter

    @app.post("/api/v1/route-context")
    async def route_context(request: Request, session: Any = Depends(mutate)) -> dict[str, Any]:
        payload = await _payload(request, RoutePlanner.MAX_REQUEST_BYTES)
        try:
            selected = adapter.validate(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store = getattr(app.state, "route_plan_store", None)
        plan = None if store is None else store.get(session.workspace_id, selected["plan_id"])
        if plan is None:
            raise HTTPException(status_code=404, detail="План маршруту недоступний або строк дії минув.")
        if not any(route.get("id") == selected["route_id"] for route in plan.get("routes", [])):
            raise HTTPException(status_code=404, detail="Маршрут у плані недоступний.")
        try:
            selected, _ = adapter.resolve_selection(plan, selected)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        cached = adapter.cached(session.workspace_id, selected["plan_id"], selected["route_id"], selected["section_index"], plan["request"]["trip_date"], selected.get("sample_chainage_m"))
        if cached is not None:
            return cached
        slots = getattr(app.state, "context_slots", None)
        if slots is None or not slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Забагато одночасних запитів контексту. Спробуйте пізніше.")
        try:
            consume_source_budget(session.workspace_id)
            response = await run_in_threadpool(adapter.build, plan, selected, app.state.static_sources, app.state.live_weather)
        finally:
            slots.release()
        adapter.remember(session.workspace_id, response)
        return deepcopy(response)
