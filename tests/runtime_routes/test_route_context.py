from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.route_planner import RoutePlanStore, RoutePlanner, register_route_endpoints
from apps.api.route_context import RouteContext, register_route_context_endpoints


NOW = datetime(2026, 10, 26, tzinfo=UTC)
VALID = {
    "origin": {"longitude": 10.7387, "latitude": 59.9139},
    "destination": {"longitude": 10.7849, "latitude": 59.9399},
    "trip_date": "2026-10-26",
    "vehicle": {"kind": "truck_6x6", "gross_mass_t": 20},
}
ROUTE = {"code": "Ok", "routes": [{"distance": 5931.5, "geometry": {"type": "LineString", "coordinates": [[10.7387, 59.9139], [10.75, 59.92], [10.7849, 59.9399]]}}]}


class Session:
    workspace_id = "workspace-a"


class StaticDouble:
    def __init__(self):
        self.full_reads = 0
        self.primitive_reads = []

    def read(self, *_):
        self.full_reads += 1
        raise AssertionError("full static read is forbidden for section context")

    def _urls_for_point(self, latitude, longitude):
        return {"terrain": "trusted-terrain", "worldcover": "trusted-worldcover"}

    def _terrain(self, latitude, longitude, url, retrieved_at):
        self.primitive_reads.append("terrain")
        return ({"elevation_m": 241.0, "surface_kind": "DSM", "support_m": 30}, {"id": "copernicus-glo-30", "status": "available", "qc": "available", "retrieved_at": retrieved_at, "data": {"vertical_unit": "m"}})

    def _land_cover(self, latitude, longitude, url, retrieved_at):
        self.primitive_reads.append("land_cover")
        return ({"class": 10, "label": "tree_cover", "support_m": 10, "reference_year": 2021}, {"id": "esa-worldcover", "status": "available", "qc": "available", "retrieved_at": retrieved_at, "data": {"static_reference_year": 2021}})


class WeatherDouble:
    def forecast(self, latitude, longitude, trip_date):
        return {
            "assessment_date": trip_date,
            "grid_point": {"latitude": latitude, "longitude": longitude, "elevation_m": 200},
            "source": {"id": "open-meteo-icon-global", "retrieved_at": "2026-10-26T00:00:00Z", "content_sha256": "sha256:abc"},
            "units": {"precipitation": "mm"},
            "series": [{"time": trip_date + "T00:00:00Z", "precipitation": 1.0, "precipitation_interval_start": "2026-10-25T23:00:00Z", "precipitation_interval_end": trip_date + "T00:00:00Z"}],
            "research_series": [{"not": "exposed"}],
            "qc": {"status": "available", "missing_variables": []},
        }


def planner():
    return RoutePlanner(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=ROUTE, request=request)), clock=lambda: NOW)


def app_and_client():
    app = FastAPI()
    app.state.static_sources = StaticDouble()
    app.state.live_weather = WeatherDouble()
    app.state.context_slots = threading.BoundedSemaphore(2)
    budgets = []
    register_route_endpoints(app, lambda: Session(), lambda: Session(), budgets.append, planner=planner())
    register_route_context_endpoints(app, lambda: Session(), lambda: Session(), budgets.append)
    return app, TestClient(app), budgets


def test_ready_plan_gets_workspace_bound_handle_and_context_uses_only_primitives():
    app, client, budgets = app_and_client()
    route = client.post("/api/v1/route-plans", json=VALID).json()

    assert route["plan_id"]
    response = client.post("/api/v1/route-context", json={"plan_id": route["plan_id"], "route_id": "route-1", "section_index": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan_id"] == route["plan_id"]
    assert payload["status"] == "available"
    assert payload["synthetic"] is False
    assert payload["evidence_scope"] == "point_sample"
    assert payload["coverage"] == "not_continuous"
    assert len(payload["sections"]) == 3
    assert payload["sections"][0]["from_m"] == 0
    assert payload["sections"][-1]["to_m"] > payload["sections"][1]["to_m"]
    assert payload["land_cover"]["reference_year"] == 2021
    assert payload["terrain"]["surface_kind"] == "DSM"
    assert payload["ground_composition"] == {"status": "unknown"}
    assert payload["weather"]["source"]["content_sha256"] == "sha256:abc"
    assert "research_series" not in payload["weather"]
    assert app.state.static_sources.full_reads == 0
    assert app.state.static_sources.primitive_reads == ["terrain", "land_cover"]
    assert budgets == ["workspace-a", "workspace-a"]


def test_context_summarizes_the_same_forecast_without_extra_requests_or_exposing_research_rows():
    class CompleteWeather(WeatherDouble):
        calls = 0

        def forecast(self, latitude, longitude, trip_date):
            self.calls += 1
            dto = super().forecast(latitude, longitude, trip_date)
            rows = []
            for hour in range(25):
                end = NOW + timedelta(hours=hour)
                rows.append({'time': end.isoformat().replace('+00:00', 'Z'), 'precipitation': 1000 if hour == 0 else 1,
                             'precipitation_interval_start': (end - timedelta(hours=1)).isoformat().replace('+00:00', 'Z'),
                             'precipitation_interval_end': end.isoformat().replace('+00:00', 'Z'),
                             'soil_temperature_0cm': -2 if hour == 0 else (999 if hour == 24 else 3), 'snow_depth': 0})
            return {**dto, 'units': {'precipitation': 'mm', 'soil_temperature_0cm': '°C', 'snow_depth': 'm'}, 'research_series': rows}

    app, client, budgets = app_and_client()
    weather = CompleteWeather(); app.state.live_weather = weather
    plan = client.post('/api/v1/route-plans', json=VALID).json()
    payload = client.post('/api/v1/route-context', json={'plan_id': plan['plan_id'], 'route_id': 'route-1', 'section_index': 0}).json()
    summary = payload['weather']['day_summary']
    assert summary['status'] == 'available'
    assert summary['precipitation']['total_mm'] == 24
    assert summary['soil_temperature']['min_c'] == -2
    assert summary['soil_temperature']['max_c'] == 3
    assert summary['snow_depth']['max_m'] == 0
    assert payload['weather']['source']['content_sha256'] == 'sha256:abc'
    assert 'research_series' not in payload['weather']
    assert weather.calls == 1
    assert budgets == ['workspace-a', 'workspace-a']


def test_context_rejects_foreign_plan_before_source_budget_or_io():
    app, client, budgets = app_and_client()
    response = client.post("/api/v1/route-context", json={"plan_id": "a" * 32, "route_id": "route-1", "section_index": 0})
    assert response.status_code == 404
    assert budgets == []
    assert app.state.static_sources.primitive_reads == []


def test_context_rejects_malformed_payload_before_source_budget():
    app, client, budgets = app_and_client()
    response = client.post("/api/v1/route-context", json={"plan_id": "not-a-handle", "route_id": "route-1", "section_index": 3})
    assert response.status_code == 422
    assert budgets == []


def test_context_returns_explicit_out_of_range_weather_without_substituting_date():
    class OutOfRangeWeather:
        def forecast(self, *_):
            from apps.api.live_data import LiveDataError
            raise LiveDataError(422, "assessment_date поза доступним семиденним горизонтом ICON Global.")

    app, client, _ = app_and_client()
    app.state.live_weather = OutOfRangeWeather()
    plan_id = client.post("/api/v1/route-plans", json=VALID).json()["plan_id"]
    payload = client.post("/api/v1/route-context", json={"plan_id": plan_id, "route_id": "route-1", "section_index": 0}).json()
    assert payload["weather"] == {"status": "date_out_of_range"}
    assert payload["status"] == "partial"


def test_context_cache_is_workspace_scoped_and_avoids_repeat_provider_io():
    app, client, budgets = app_and_client()
    plan_id = client.post("/api/v1/route-plans", json=VALID).json()["plan_id"]
    request = {"plan_id": plan_id, "route_id": "route-1", "section_index": 0}
    first = client.post("/api/v1/route-context", json=request)
    second = client.post("/api/v1/route-context", json=request)

    assert first.json() == second.json()
    assert app.state.static_sources.primitive_reads == ["terrain", "land_cover"]
    assert budgets == ["workspace-a", "workspace-a"]


def test_plan_store_does_not_expose_foreign_or_expired_snapshots():
    now = [0.0]
    store = RoutePlanStore(monotonic_clock=lambda: now[0])
    handle = store.put("workspace-a", {"routes": []})
    assert store.get("workspace-b", handle) is None
    now[0] = RoutePlanStore.TTL_SECONDS + 1
    assert store.get("workspace-a", handle) is None


def test_context_cache_expires_after_five_minutes():
    now = [0.0]
    context = RouteContext(monotonic_clock=lambda: now[0])
    response = {"status": "partial", "plan_id": "a" * 32, "route_id": "route-1", "section_index": 0, "trip_date": "2026-10-26"}
    context.remember("workspace-a", response)
    assert context.cached("workspace-a", "a" * 32, "route-1", 0, "2026-10-26") == response
    now[0] = RouteContext.CACHE_TTL_SECONDS + 1
    assert context.cached("workspace-a", "a" * 32, "route-1", 0, "2026-10-26") is None


def test_offroad_context_includes_soil_local_slope_and_tree_cover_without_full_static_read():
    from apps.api.terrain_planner import TerrainPlanner
    calls = []
    class EvidenceDouble:
        def read(self, latitude, longitude):
            calls.append((latitude, longitude))
            return {"ground_composition": {"status": "partial", "composition": {"sand": 59.8, "silt": 32.9, "clay": 3.2}},
                    "local_terrain": {"slope_deg": 5.9}, "vegetation": {"tree_cover_percent": 96.4},
                    "sources": [{"id": "soilgrids", "status": "partial"}, {"id": "copernicus-glo-30", "status": "available"}, {"id": "esa-worldcover", "status": "available"}]}
    context = RouteContext(terrain_evidence_factory=lambda _: EvidenceDouble())
    plan = TerrainPlanner().plan(VALID)
    selected = {"plan_id": "a" * 32, "route_id": "transect-1", "section_index": 1}
    static = StaticDouble()
    result = context.build(plan, selected, static, WeatherDouble())
    assert result["ground_composition"]["composition"]["sand"] == 59.8
    assert result["local_terrain"]["slope_deg"] == 5.9
    assert result["vegetation"]["tree_cover_percent"] == 96.4
    assert result["status"] == "partial" and result["coverage"] == "not_continuous"
    assert calls == [(result["sections"][1]["point"]["latitude"], result["sections"][1]["point"]["longitude"])]
    assert static.full_reads == 0


def test_offroad_evidence_failure_preserves_existing_height_cover_and_weather():
    from apps.api.terrain_planner import TerrainPlanner
    class BrokenEvidence:
        def read(self, *_):
            raise RuntimeError("internal provider failure")
    context = RouteContext(terrain_evidence_factory=lambda _: BrokenEvidence())
    result = context.build(TerrainPlanner().plan(VALID), {"plan_id": "a" * 32, "route_id": "transect-1", "section_index": 0}, StaticDouble(), WeatherDouble())
    assert result["status"] == "partial"
    assert result["terrain"]["elevation_m"] == 241
    assert result["ground_composition"]["status"] == "unavailable"
    assert result["weather"]["assessment_date"] == VALID["trip_date"]
    assert "internal provider" not in str(result)


def test_offroad_context_adds_separate_canopy_density_at_selected_point():
    from apps.api.terrain_planner import TerrainPlanner
    calls = []
    class CanopyDouble:
        def read_point(self, latitude, longitude):
            calls.append((latitude, longitude))
            return {"percent": 77, "reference_year": 2018, "resolution_m": 10}, {"id": "clms-tree-cover-density", "status": "available"}
    context = RouteContext(canopy_source=CanopyDouble(), terrain_evidence_factory=lambda _: None)
    selected = {"plan_id": "a" * 32, "route_id": "transect-1", "section_index": 1}
    result = context.build(TerrainPlanner().plan(VALID), selected, StaticDouble(), WeatherDouble())
    assert result["canopy_cover"]["percent"] == 77
    assert result["canopy_cover"]["reference_year"] == 2018
    assert calls == [(result["sections"][1]["point"]["latitude"], result["sections"][1]["point"]["longitude"])]
    assert next(source for source in result["sources"] if source["id"] == "clms-tree-cover-density")["extraction_scope"] == "canopy_point"


def test_canopy_failure_preserves_other_context_and_hides_exception_details():
    from apps.api.terrain_planner import TerrainPlanner
    class BrokenCanopy:
        def read_point(self, *_):
            raise RuntimeError("private backend details")
    context = RouteContext(canopy_source=BrokenCanopy(), terrain_evidence_factory=lambda _: None)
    result = context.build(TerrainPlanner().plan(VALID), {"plan_id": "a" * 32, "route_id": "transect-1", "section_index": 0}, StaticDouble(), WeatherDouble())
    assert result["status"] == "partial" and result["canopy_cover"]["percent"] is None
    assert result["terrain"]["elevation_m"] == 241 and result["land_cover"]["class"] == 10
    assert result["weather"]["assessment_date"] == VALID["trip_date"]
    assert "private backend details" not in str(result)


def test_road_context_never_queries_canopy_source():
    calls = []
    class CanopyDouble:
        def read_point(self, *args):
            calls.append(args)
            raise AssertionError("road context must not call canopy source")
    context = RouteContext(canopy_source=CanopyDouble())
    result = context.build(planner().plan(VALID), {"plan_id": "a" * 32, "route_id": "route-1", "section_index": 0}, StaticDouble(), WeatherDouble())
    assert calls == [] and "canopy_cover" not in result
