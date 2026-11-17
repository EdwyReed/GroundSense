from __future__ import annotations

from datetime import UTC, datetime, timedelta
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.route_context import RouteContext, register_route_context_endpoints
from apps.api.route_planner import RoutePlanStore
from apps.api.terrain_planner import TerrainPlanner
from tests.runtime_routes.test_route_context import Session, StaticDouble, VALID

DIGEST = "sha256:4ef282407d6e88b8414b9381349b45c8c1feb3a82988416697e83db9decda4b4"


class SectionWeather:
    def __init__(self):
        self.calls = []

    def forecast(self, *_):
        raise AssertionError("off-road context must use its existing section weather call")

    def forecast_for_section(self, latitude, longitude, trip_date):
        self.calls.append((latitude, longitude, trip_date))
        start = datetime.fromisoformat(trip_date).replace(tzinfo=UTC)
        rows = [
            {
                "time": (start + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
                "precipitation": 0,
                "soil_temperature_0cm": 1,
                "snow_depth": 0,
                "soil_moisture_0_to_1cm": 0.296 + hour / 10000,
                "soil_moisture_1_to_3cm": 0.298 + hour / 10000,
                "soil_moisture_3_to_9cm": 0.306 + hour / 10000,
            }
            for hour in range(24)
        ]
        return {
            "assessment_date": trip_date,
            "requested_point": {"latitude": latitude, "longitude": longitude},
            "grid_point": {"latitude": 60, "longitude": 10.75},
            "source": {"id": "open-meteo-icon-global", "model": "icon_global", "content_sha256": DIGEST},
            "units": {"precipitation": "mm", "soil_temperature_0cm": "°C", "snow_depth": "m", "soil_moisture_0_to_1cm": "m³/m³", "soil_moisture_1_to_3cm": "m³/m³", "soil_moisture_3_to_9cm": "m³/m³"},
            "series": rows,
            "research_series": rows,
            "antecedent_series": [],
            "qc": {"status": "available", "missing_variables": []},
        }


def test_endpoint_offroad_weather_adds_bound_soil_water_from_one_call_at_chosen_line_point():
    plan = TerrainPlanner().plan(VALID)
    probe = RouteContext()
    section = probe._sections(plan["routes"][0]["geometry"])[1]
    chainage = section["from_m"] + 10
    weather = SectionWeather()
    app = FastAPI()
    app.state.static_sources = StaticDouble()
    app.state.live_weather = weather
    app.state.context_slots = threading.BoundedSemaphore(2)
    app.state.route_plan_store = RoutePlanStore()
    plan_id = app.state.route_plan_store.put("workspace-a", plan)
    register_route_context_endpoints(app, lambda: Session(), lambda: Session(), lambda _: None)

    response = TestClient(app).post("/api/v1/route-context", json={"plan_id": plan_id, "route_id": "transect-1", "section_index": 1, "sample_chainage_m": chainage})

    assert response.status_code == 200
    result = response.json()
    chosen = result["sample_selection"]["point"]
    assert weather.calls == [(chosen["latitude"], chosen["longitude"], VALID["trip_date"])]
    assert result["weather"]["source"]["content_sha256"] == DIGEST
    assert result["weather"]["requested_point"] == chosen
    assert result["weather"]["soil_water"]["source_sha256"] == DIGEST
    assert result["weather"]["soil_water"]["requested_point"] == chosen
    assert result["weather"]["soil_water"]["grid_point"] == {"latitude": 60.0, "longitude": 10.75}
    assert result["weather"]["soil_water"]["status"] == "available"
    assert result["weather"]["soil_water"]["layers"][0]["known_samples"] == 24
    assert "research_series" not in result["weather"]
    assert "antecedent_precipitation" in result["weather"] and "day_summary" in result["weather"] and "outlook" in result["weather"]
