"""Unsnapped terrain-analysis transects, explicitly not off-road routing."""
from __future__ import annotations

from datetime import UTC, datetime
import math
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request

from apps.api.route_planner import RoutePlanner, _payload


class TerrainPlanner:
    MAX_DISTANCE_M = 20_000

    def plan(self, payload: Any) -> dict[str, Any]:
        request = RoutePlanner().validate_request(payload)
        origin, destination = request["origin"], request["destination"]
        distance = RoutePlanner._distance_m(origin, destination)
        if not 1 <= distance <= self.MAX_DISTANCE_M:
            raise ValueError("Для аналізу місцевості оберіть різні точки на відстані від 1 м до 20 км.")
        if abs(origin["longitude"] - destination["longitude"]) > 180:
            raise ValueError("Аналіз через меридіан 180° поки не підтримується.")
        coordinates = self._transect(origin, destination, distance)
        return {"request": request, "status": "ready", "analysis_kind": "terrain_transect",
                "routes": [{"id": "transect-1", "name": "Профіль місцевості", "distance_m": distance,
                            "geometry": {"type": "LineString", "coordinates": coordinates}, "geometry_kind": "analysis_transect",
                            "conditions": {"status": "not_assessed", "summary_uk": "Лінія аналізу, не шлях проїзду"},
                            "surface": {"paved_m": None, "unpaved_m": None}, "segments": []}],
                "source": {"id": "user-transect", "profile": "not_routed", "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")},
                "vehicle_assessment": "not_assessed", "date_assessment": "not_assessed", "synthetic": False,
                "warnings_uk": ["Це лінія вибірки місцевості між A і B, не маршрут і не підтвердження можливості проїзду.",
                                "Три точкові вибірки не описують усі перешкоди між ними."]}

    @staticmethod
    def _transect(origin: dict[str, Any], destination: dict[str, Any], distance: float) -> list[list[float]]:
        lat1, lon1, lat2, lon2 = map(math.radians, (origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"]))
        bearing = math.atan2(math.sin(lon2 - lon1) * math.cos(lat2), math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
        points = [[origin["longitude"], origin["latitude"]]]
        for index in range(1, 24):
            angle = distance / 6_371_000 * index / 24
            lat = math.asin(max(-1, min(1, math.sin(lat1) * math.cos(angle) + math.cos(lat1) * math.sin(angle) * math.cos(bearing))))
            lon = lon1 + math.atan2(math.sin(bearing) * math.sin(angle) * math.cos(lat1), math.cos(angle) - math.sin(lat1) * math.sin(lat))
            points.append([((math.degrees(lon) + 180) % 360) - 180, math.degrees(lat)])
        points.append([destination["longitude"], destination["latitude"]])
        if any(abs(right[0] - left[0]) > 180 for left, right in zip(points, points[1:])):
            raise ValueError("Аналіз через меридіан 180° поки не підтримується.")
        return points


def register_terrain_endpoints(app: FastAPI, mutate: Callable[..., Any], consume_source_budget: Callable[[str], None]) -> None:
    adapter = TerrainPlanner()

    @app.post("/api/v1/terrain-plans")
    async def create_terrain_plan(request: Request, session: Any = Depends(mutate)) -> dict[str, Any]:
        payload = await _payload(request, RoutePlanner.MAX_REQUEST_BYTES)
        try:
            result = adapter.plan(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        consume_source_budget(session.workspace_id)
        result["plan_id"] = app.state.route_plan_store.put(session.workspace_id, result)
        return result
