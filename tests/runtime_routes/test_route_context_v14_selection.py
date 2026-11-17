from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.route_context import RouteContext, register_route_context_endpoints
from apps.api.route_planner import RoutePlanStore
from apps.api.terrain_planner import TerrainPlanner
from tests.runtime_routes.test_route_context import Session, StaticDouble, VALID, WeatherDouble, planner


class RecordingStatic(StaticDouble):
    def __init__(self):
        super().__init__()
        self.points = []

    def _urls_for_point(self, latitude, longitude):
        self.points.append((latitude, longitude))
        return super()._urls_for_point(latitude, longitude)


class RecordingWeather(WeatherDouble):
    def __init__(self):
        self.points = []

    def forecast(self, latitude, longitude, trip_date):
        self.points.append((latitude, longitude))
        return super().forecast(latitude, longitude, trip_date)


def terrain_endpoint():
    app = FastAPI()
    app.state.static_sources = RecordingStatic()
    app.state.live_weather = RecordingWeather()
    app.state.context_slots = threading.BoundedSemaphore(2)
    app.state.route_plan_store = RoutePlanStore()
    plan = TerrainPlanner().plan(VALID)
    plan_id = app.state.route_plan_store.put("workspace-a", plan)
    budgets = []
    register_route_context_endpoints(app, lambda: Session(), lambda: Session(), budgets.append)
    return app, TestClient(app), plan_id, budgets


def test_chosen_chainages_in_one_section_use_distinct_resolved_points_and_provider_arguments():
    app, client, plan_id, budgets = terrain_endpoint()
    context = app.state.route_context
    plan = app.state.route_plan_store.get("workspace-a", plan_id)
    section = context._sections(plan["routes"][0]["geometry"])[1]
    first_chainage = section["from_m"] + 10
    second_chainage = first_chainage + 10
    base = {"plan_id": plan_id, "route_id": "transect-1", "section_index": 1}

    first = client.post("/api/v1/route-context", json={**base, "sample_chainage_m": first_chainage})
    second = client.post("/api/v1/route-context", json={**base, "sample_chainage_m": second_chainage})

    assert first.status_code == second.status_code == 200
    left, right = first.json(), second.json()
    assert left["sample_selection"]["kind"] == "line_chainage"
    assert left["sample_selection"]["chainage_m"] == first_chainage
    assert right["sample_selection"]["chainage_m"] == second_chainage
    assert left["sample_selection"]["point"] != right["sample_selection"]["point"]
    first_point = (left["sample_selection"]["point"]["latitude"], left["sample_selection"]["point"]["longitude"])
    second_point = (right["sample_selection"]["point"]["latitude"], right["sample_selection"]["point"]["longitude"])
    assert app.state.static_sources.points == [first_point, first_point, second_point, second_point]
    assert app.state.live_weather.points == [first_point, second_point]
    assert budgets == ["workspace-a", "workspace-a"]


@pytest.mark.parametrize("value", [None, True, "10", -1, 20_001, 10 ** 400])
def test_invalid_chainage_rejects_before_source_budget_or_provider_work(value):
    app, client, plan_id, budgets = terrain_endpoint()
    response = client.post("/api/v1/route-context", json={"plan_id": plan_id, "route_id": "transect-1", "section_index": 0, "sample_chainage_m": value})

    assert response.status_code == 422
    assert budgets == []
    assert app.state.static_sources.points == []
    assert app.state.live_weather.points == []


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_chainage_rejects_before_source_budget_or_provider_work(value):
    app, client, plan_id, budgets = terrain_endpoint()
    response = client.post(
        "/api/v1/route-context",
        content=f'{{"plan_id":"{plan_id}","route_id":"transect-1","section_index":0,"sample_chainage_m":{value}}}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert budgets == []
    assert app.state.static_sources.points == []
    assert app.state.live_weather.points == []


def test_chainage_outside_selected_section_rejects_before_budget():
    app, client, plan_id, budgets = terrain_endpoint()
    plan = app.state.route_plan_store.get("workspace-a", plan_id)
    section = app.state.route_context._sections(plan["routes"][0]["geometry"])[1]
    response = client.post("/api/v1/route-context", json={"plan_id": plan_id, "route_id": "transect-1", "section_index": 1, "sample_chainage_m": section["from_m"] - 1})

    assert response.status_code == 422
    assert budgets == []
    assert app.state.static_sources.points == []


@pytest.mark.parametrize("coordinates", [
    [[10.0, 60.0], [float("nan"), 60.0]],
    [[10.0, 60.0], [10 ** 400, 60.0]],
    [[10.0, 60.0], [10.2, 60.0], [10.0, 60.0], [10.2, 60.0]],
])
def test_invalid_or_detouring_stored_geometry_rejects_before_budget(coordinates):
    app, client, plan_id, budgets = terrain_endpoint()
    plan = app.state.route_plan_store.get("workspace-a", plan_id)
    plan["routes"][0]["geometry"]["coordinates"] = coordinates
    plan_id = app.state.route_plan_store.put("workspace-a", plan)
    response = client.post("/api/v1/route-context", json={"plan_id": plan_id, "route_id": "transect-1", "section_index": 0, "sample_chainage_m": 0})

    assert response.status_code == 422
    assert budgets == []
    assert app.state.static_sources.points == []


def test_zero_chainage_isolated_from_legacy_cache_and_road_selection_is_rejected():
    app, client, plan_id, budgets = terrain_endpoint()
    selected = {"plan_id": plan_id, "route_id": "transect-1", "section_index": 0}
    legacy = client.post("/api/v1/route-context", json=selected)
    zero = client.post("/api/v1/route-context", json={**selected, "sample_chainage_m": 0})
    assert legacy.status_code == zero.status_code == 200
    assert "sample_selection" not in legacy.json()
    assert zero.json()["sample_selection"]["chainage_m"] == 0
    assert app.state.static_sources.points[0] != app.state.static_sources.points[2]
    assert budgets == ["workspace-a", "workspace-a"]

    road_app = FastAPI()
    road_app.state.static_sources = RecordingStatic()
    road_app.state.live_weather = RecordingWeather()
    road_app.state.context_slots = threading.BoundedSemaphore(2)
    road_app.state.route_plan_store = RoutePlanStore()
    road_id = road_app.state.route_plan_store.put("workspace-a", planner().plan(VALID))
    road_budgets = []
    register_route_context_endpoints(road_app, lambda: Session(), lambda: Session(), road_budgets.append)
    response = TestClient(road_app).post("/api/v1/route-context", json={"plan_id": road_id, "route_id": "route-1", "section_index": 0, "sample_chainage_m": 0})
    assert response.status_code == 422
    assert road_budgets == []
    assert road_app.state.static_sources.points == []
