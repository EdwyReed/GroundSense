"""Bounded public road routing and place lookup for the route-first UI.

This adapter only returns geometry from fixed public providers.  It deliberately
makes no claim about truck access, ground bearing, surface, or date suitability.
"""
from __future__ import annotations

import json
import math
import secrets
import threading
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Callable

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool


class RoutePlanner:
    """Small fixed-provider adapter with injectable transport for tests."""

    OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
    PHOTON_URL = "https://photon.komoot.io/api/"
    MAX_REQUEST_BYTES = 8_192
    MAX_RESPONSE_BYTES = 1_048_576
    MAX_LABEL_LENGTH = 120
    MAX_QUERY_LENGTH = 120
    MAX_ALTERNATIVES = 3
    MAX_GEOMETRY_POINTS = 10_000
    MAX_TRIP_DISTANCE_M = 300_000
    MAX_ROUTE_DISTANCE_M = 600_000
    MAX_SNAP_DISTANCE_M = 2_000

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float = 8.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("Некоректний час очікування маршрутизатора.")
        if type(max_response_bytes) is not int or not 1_024 <= max_response_bytes <= self.MAX_RESPONSE_BYTES:
            raise ValueError("Некоректне обмеження відповіді маршрутизатора.")
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes

    def validate_request(self, payload: Any) -> dict[str, Any]:
        request = self._request(payload)
        origin, destination = request["origin"], request["destination"]
        if self._distance_m(origin, destination) > self.MAX_TRIP_DISTANCE_M:
            raise ValueError("Точки маршруту надто далекі одна від одної.")
        return request

    def plan(self, payload: Any) -> dict[str, Any]:
        request = self.validate_request(payload)
        origin, destination = request["origin"], request["destination"]

        path = f"{self.OSRM_URL}/{origin['longitude']:.7f},{origin['latitude']:.7f};{destination['longitude']:.7f},{destination['latitude']:.7f}"
        try:
            raw = self._get_json(path, params={"overview": "full", "geometries": "geojson", "alternatives": "true", "steps": "false"})
        except _ProviderFailure:
            return self._route_status(request, "unavailable", "Сервіс дорожньої геометрії тимчасово недоступний.")

        if raw.get("code") in ("NoRoute", "NoSegment"):
            return self._route_status(request, "no_route", "Між вибраними точками дорожній маршрут не знайдено.")
        if raw.get("code") != "Ok" or not isinstance(raw.get("routes"), list):
            return self._route_status(request, "unavailable", "Сервіс дорожньої геометрії повернув некоректну відповідь.")

        try:
            routes = self._routes(raw["routes"], origin, destination)
        except ValueError:
            return self._route_status(request, "unavailable", "Сервіс дорожньої геометрії повернув некоректні дані.")
        if not routes:
            return self._route_status(request, "no_route", "Між вибраними точками дорожній маршрут не знайдено.")

        return {
            "request": request,
            "status": "ready",
            "routes": routes,
            "source": {"id": "osrm", "profile": "car", "retrieved_at": self._timestamp()},
            "vehicle_assessment": "not_assessed",
            "date_assessment": "not_assessed",
            "synthetic": False,
            "warnings_uk": ["Дорожня геометрія: автомобільний профіль, не перевірка проїзду вантажівки."],
        }

    def places(self, query: Any) -> dict[str, Any]:
        q = self._query(query)
        try:
            raw = self._get_json(self.PHOTON_URL, params={"q": q, "limit": "5"})
        except _ProviderFailure:
            return {"places": [], "source": {"id": "photon"}, "status": "unavailable"}
        features = raw.get("features")
        if not isinstance(features, list):
            return {"places": [], "source": {"id": "photon"}, "status": "unavailable"}

        places: list[dict[str, Any]] = []
        seen: set[tuple[float, float, str]] = set()
        for feature in features[:10]:
            place = self._place(feature)
            if place is None:
                continue
            key = (place["longitude"], place["latitude"], place["label"])
            if key not in seen:
                seen.add(key)
                places.append(place)
            if len(places) == 5:
                break
        return {"places": places, "source": {"id": "photon"}, "status": "ready"}

    def _get_json(self, url: str, *, params: dict[str, str]) -> dict[str, Any]:
        data = bytearray()
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout_seconds, follow_redirects=False) as client:
                with client.stream("GET", url, params=params, headers={"Accept": "application/json", "User-Agent": "GroundSense-route-planner/2"}) as response:
                    osrm_no_segment = response.status_code == 400 and url.startswith(self.OSRM_URL + "/")
                    if (response.is_error and not osrm_no_segment) or response.is_redirect:
                        raise _ProviderFailure()
                    for chunk in response.iter_bytes(chunk_size=8_192):
                        data.extend(chunk)
                        if len(data) > self._max_response_bytes:
                            raise _ProviderFailure()
        except (httpx.HTTPError, ValueError, UnicodeError) as exc:
            if isinstance(exc, _ProviderFailure):
                raise
            raise _ProviderFailure() from exc
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            raise _ProviderFailure() from exc
        if not isinstance(parsed, dict):
            raise _ProviderFailure()
        return parsed

    def _request(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Некоректний запит маршруту.")
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Некоректний запит маршруту.") from exc
        if len(encoded) > self.MAX_REQUEST_BYTES:
            raise ValueError("Запит маршруту завеликий.")
        return {
            "origin": self._point(payload.get("origin"), "початкову"),
            "destination": self._point(payload.get("destination"), "кінцеву"),
            "trip_date": self._date(payload.get("trip_date")),
            "vehicle": self._vehicle(payload.get("vehicle")),
        }

    def _point(self, value: Any, noun: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"Вкажіть {noun} точку.")
        longitude = self._number(value.get("longitude"), "longitude", -180, 180)
        latitude = self._number(value.get("latitude"), "latitude", -90, 90)
        label = value.get("label")
        if label is not None:
            if not isinstance(label, str) or not label.strip() or len(label) > self.MAX_LABEL_LENGTH or any(ord(char) < 32 for char in label):
                raise ValueError("Некоректна назва точки.")
            label = label.strip()
        result: dict[str, Any] = {"longitude": longitude, "latitude": latitude}
        if label is not None:
            result["label"] = label
        return result

    @staticmethod
    def _number(value: Any, name: str, lower: float, upper: float) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not lower <= value <= upper:
            raise ValueError(f"Некоректне значення {name}.")
        return float(value)

    def _date(self, value: Any) -> str:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("Некоректна дата поїздки.")
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError("Некоректна дата поїздки.") from exc

    def _vehicle(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or not isinstance(value.get("kind"), str) or value["kind"] not in {"car", "truck_4x4", "truck_6x6"}:
            raise ValueError("Некоректний тип транспорту.")
        mass = self._number(value.get("gross_mass_t"), "маса", 0, 1_000)
        if mass <= 0:
            raise ValueError("Некоректна маса транспорту.")
        return {"kind": value["kind"], "gross_mass_t": mass}

    def _routes(self, source_routes: list[Any], origin: dict[str, Any], destination: dict[str, Any]) -> list[dict[str, Any]]:
        routes = []
        for index, source in enumerate(source_routes[: self.MAX_ALTERNATIVES], 1):
            if not isinstance(source, dict):
                raise ValueError("invalid route")
            distance = self._number(source.get("distance"), "distance", 0, self.MAX_ROUTE_DISTANCE_M)
            geometry = self._geometry(source.get("geometry"))
            if self._distance_m(origin, {"longitude": geometry["coordinates"][0][0], "latitude": geometry["coordinates"][0][1]}) > self.MAX_SNAP_DISTANCE_M:
                raise ValueError("invalid snap")
            if self._distance_m(destination, {"longitude": geometry["coordinates"][-1][0], "latitude": geometry["coordinates"][-1][1]}) > self.MAX_SNAP_DISTANCE_M:
                raise ValueError("invalid snap")
            # Check the entire polyline, not just its snapped endpoints. These
            # are coarse response-integrity bounds, not a suitability model.
            geometry_length = 0.0
            previous = {"longitude": geometry["coordinates"][0][0], "latitude": geometry["coordinates"][0][1]}
            for longitude, latitude in geometry["coordinates"][1:]:
                current = {"longitude": longitude, "latitude": latitude}
                geometry_length += self._distance_m(previous, current)
                if geometry_length > self.MAX_ROUTE_DISTANCE_M:
                    raise ValueError("route geometry exceeds bounded search")
                previous = current
            if distance <= 0 or geometry_length <= 0 or distance > geometry_length * 2 + 2_000 or geometry_length > distance * 2 + 2_000:
                raise ValueError("route distance contradicts geometry")
            routes.append({
                "id": f"route-{index}",
                "name": "Основний" if index == 1 else f"Альтернатива {index}",
                "distance_m": distance,
                "geometry": geometry,
                "conditions": {"status": "not_assessed", "summary_uk": "Умови ґрунту не оцінено"},
                "surface": {"paved_m": None, "unpaved_m": None},
                "segments": [],
            })
        return routes

    def _geometry(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("type") != "LineString" or not isinstance(value.get("coordinates"), list):
            raise ValueError("invalid geometry")
        source = value["coordinates"]
        if not 2 <= len(source) <= self.MAX_GEOMETRY_POINTS:
            raise ValueError("invalid geometry")
        coordinates: list[list[float]] = []
        for point in source:
            if not isinstance(point, list) or len(point) < 2:
                raise ValueError("invalid geometry")
            coordinates.append([self._number(point[0], "longitude", -180, 180), self._number(point[1], "latitude", -90, 90)])
        return {"type": "LineString", "coordinates": coordinates}

    def _place(self, feature: Any) -> dict[str, Any] | None:
        if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict) or feature["geometry"].get("type") != "Point":
            return None
        coordinates = feature["geometry"].get("coordinates")
        properties = feature.get("properties")
        if not isinstance(coordinates, list) or len(coordinates) < 2 or not isinstance(properties, dict):
            return None
        try:
            longitude = self._number(coordinates[0], "longitude", -180, 180)
            latitude = self._number(coordinates[1], "latitude", -90, 90)
        except ValueError:
            return None
        parts = [properties.get(key) for key in ("name", "city", "county", "state", "country")]
        label = ", ".join(dict.fromkeys(part.strip() for part in parts if isinstance(part, str) and part.strip()))
        if not label or len(label) > self.MAX_LABEL_LENGTH or any(ord(char) < 32 for char in label):
            return None
        return {"longitude": longitude, "latitude": latitude, "label": label}

    def _query(self, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("Пошуковий запит має бути текстом.")
        query = value.strip()
        if not query or len(query) > self.MAX_QUERY_LENGTH or any(ord(char) < 32 for char in query):
            raise ValueError("Пошуковий запит некоректний.")
        return query

    def _route_status(self, request: dict[str, Any], status: str, warning: str) -> dict[str, Any]:
        return {
            "request": request,
            "status": status,
            "routes": [],
            "source": {"id": "osrm", "profile": "car", "retrieved_at": self._timestamp()},
            "vehicle_assessment": "not_assessed",
            "date_assessment": "not_assessed",
            "synthetic": False,
            "warnings_uk": [warning, "Дорожня геометрія: автомобільний профіль, не перевірка проїзду вантажівки."],
        }

    def _timestamp(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValueError("clock має повертати datetime.")
        return value.replace(tzinfo=UTC).astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _distance_m(first: dict[str, Any], second: dict[str, Any]) -> float:
        lat1, lon1 = math.radians(first["latitude"]), math.radians(first["longitude"])
        lat2, lon2 = math.radians(second["latitude"]), math.radians(second["longitude"])
        a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        return 6_371_000 * 2 * math.asin(math.sqrt(a))


class _ProviderFailure(Exception):
    pass


class RoutePlanStore:
    """Thread-safe, workspace-scoped short-lived route-plan snapshots."""

    MAX_ENTRIES = 16
    TTL_SECONDS = 900.0

    def __init__(self, *, monotonic_clock: Callable[[], float] = monotonic) -> None:
        self._clock = monotonic_clock
        self._items: OrderedDict[str, tuple[float, str, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, workspace_id: str, plan: dict[str, Any]) -> str:
        handle = secrets.token_hex(16)
        with self._lock:
            self._purge()
            self._items[handle] = (self._clock(), workspace_id, deepcopy(plan))
            self._items.move_to_end(handle)
            while len(self._items) > self.MAX_ENTRIES:
                self._items.popitem(last=False)
        return handle

    def get(self, workspace_id: str, handle: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge()
            row = self._items.get(handle)
            if row is None or row[1] != workspace_id:
                return None
            self._items.move_to_end(handle)
            return deepcopy(row[2])

    def _purge(self) -> None:
        now = self._clock()
        for key, (saved, _, _) in tuple(self._items.items()):
            if now - saved > self.TTL_SECONDS:
                self._items.pop(key, None)


def register_route_endpoints(
    app: FastAPI,
    session_for: Callable[..., Any],
    mutate: Callable[..., Any],
    consume_source_budget: Callable[[str], None],
    *,
    planner: RoutePlanner | None = None,
) -> None:
    """Register endpoints before the generic `/api/v1/{kind}` handlers."""
    adapter = planner or RoutePlanner()
    app.state.route_planner = adapter
    app.state.route_plan_store = RoutePlanStore()

    @app.post("/api/v1/route-plans")
    async def create_route_plan(request: Request, session: Any = Depends(mutate)) -> dict[str, Any]:
        payload = await _payload(request, adapter.MAX_REQUEST_BYTES)
        try:
            validated = adapter.validate_request(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        consume_source_budget(session.workspace_id)
        result = await run_in_threadpool(adapter.plan, validated)
        if result.get("status") == "ready":
            result["plan_id"] = app.state.route_plan_store.put(session.workspace_id, result)
        return result

    @app.get("/api/v1/places")
    def find_places(q: str | None = None, session: Any = Depends(session_for)) -> dict[str, Any]:
        try:
            query = adapter._query(q)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        consume_source_budget(session.workspace_id)
        return adapter.places(query)


async def _payload(request: Request, maximum: int) -> dict[str, Any]:
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > maximum:
                raise HTTPException(status_code=413, detail="Запит маршруту завеликий.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некоректна довжина запиту.") from exc
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail="Запит маршруту завеликий.")
        raw.extend(chunk)
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise HTTPException(status_code=422, detail="Некоректний JSON маршруту.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Некоректний запит маршруту.")
    return payload
