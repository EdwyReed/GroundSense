from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.route_context import RouteContext, register_route_context_endpoints
from apps.api.route_planner import RoutePlanStore
from apps.api.terrain_planner import TerrainPlanner
from tests.runtime_routes.test_route_context import StaticDouble, VALID, WeatherDouble
from tests.runtime_routes.test_surface_observation_context import SurfaceDouble


def selected():
    return {"plan_id": "a" * 32, "route_id": "transect-1", "section_index": 0}


def complete_evidence():
    return {"ground_composition": {"status": "partial", "composition": {"sand": 50.0, "silt": 30.0, "clay": 17.4}},
            "local_terrain": {"slope_deg": 5.9}, "vegetation": {"tree_cover_percent": 60.0},
            "sources": [{"id": "soilgrids", "status": "partial", "retrieved_at": "2026-10-26T00:00:00Z", "content_sha256": "sha256:soil"},
                        {"id": "copernicus-glo-30", "status": "available"}, {"id": "esa-worldcover", "status": "available"}]}


def test_four_independent_auxiliary_sources_overlap_without_dropping_any_result():
    gate = threading.Barrier(4, timeout=2)
    arrivals = []
    lock = threading.Lock()

    def enter(name):
        with lock:
            arrivals.append(name)
        gate.wait()

    class Evidence:
        def read(self, *_):
            enter("terrain")
            return complete_evidence()

    class Weather(WeatherDouble):
        def forecast(self, *args):
            enter("weather")
            return super().forecast(*args)

    class Canopy:
        def read_point(self, *_):
            enter("canopy")
            return {"percent": 73, "reference_year": 2018, "resolution_m": 10}, {"id": "clms-tree-cover-density", "status": "available"}

    class Surface(SurfaceDouble):
        def read_point(self, *args):
            enter("surface")
            return super().read_point(*args)

    context = RouteContext(terrain_evidence_factory=lambda _: Evidence(), canopy_source=Canopy(), surface_observation=Surface())
    result = context.build(TerrainPlanner().plan(VALID), selected(), StaticDouble(), Weather())

    assert not gate.broken, "independent auxiliary reads remained serial"
    assert sorted(arrivals) == ["canopy", "surface", "terrain", "weather"]
    assert result["ground_composition"]["composition"]["clay"] == 17.4
    assert result["weather"]["assessment_date"] == VALID["trip_date"]
    assert result["canopy_cover"]["percent"] == 73
    assert result["surface_observation"]["scene_age_days"] == 1
    assert [source["id"] for source in result["sources"]] == [
        "esa-worldcover", "copernicus-glo-30", "open-meteo-icon-global", "soilgrids", "copernicus-glo-30", "esa-worldcover", "clms-tree-cover-density", "sentinel-2-l2a"]


def test_new_trip_date_reuses_only_static_evidence_with_original_provenance_and_deep_copies():
    calls = []

    class Evidence:
        def read(self, *args):
            calls.append(args)
            return complete_evidence()

    surface = SurfaceDouble()
    context = RouteContext(terrain_evidence_factory=lambda _: Evidence(), surface_observation=surface)
    static = StaticDouble()
    first = context.build(TerrainPlanner().plan(VALID), selected(), static, WeatherDouble())
    first["ground_composition"]["composition"]["sand"] = 99
    first["sources"][3]["retrieved_at"] = "mutated"
    next_trip = {**VALID, "trip_date": "2026-10-27", "vehicle": {"kind": "truck_6x6", "gross_mass_t": 22}}
    second = context.build(TerrainPlanner().plan(next_trip), {**selected(), "plan_id": "b" * 32}, static, WeatherDouble())

    assert len(calls) == 1, "changing the trip date repeated expensive static evidence reads"
    assert second["ground_composition"]["composition"]["sand"] == 50
    soil_source = next(source for source in second["sources"] if source["id"] == "soilgrids")
    assert soil_source["retrieved_at"] == "2026-10-26T00:00:00Z"
    assert soil_source["content_sha256"] == "sha256:soil" and soil_source["cached"] is True
    assert second["plan_id"] == "b" * 32 and second["trip_date"] == next_trip["trip_date"]
    assert second["weather"]["assessment_date"] == next_trip["trip_date"]
    assert [call[2] for call in surface.calls] == ["2026-10-26", "2026-10-27"]


def test_static_evidence_cache_has_exact_point_adapter_ttl_and_lru_boundaries():
    now, calls = [0.0], []

    class Evidence:
        def read(self, *args):
            calls.append(args)
            return complete_evidence()

    context = RouteContext(terrain_evidence_factory=lambda _: Evidence(), monotonic_clock=lambda: now[0])
    context.TERRAIN_CACHE_MAX_ENTRIES = 2
    static = StaticDouble()
    a = {"latitude": 60.0, "longitude": 10.0}
    b = {**a, "longitude": 10.00000001}
    c = {**a, "longitude": 11.0}
    read = lambda adapter, point: context._terrain_extra(adapter, point, "2026-10-26T00:00:00Z")
    read(static, a); read(static, b)
    assert len(calls) == 2
    read(static, a)  # a is now most-recent, so adding c evicts b.
    read(static, c)
    assert len(context._terrain_cache) == 2 and len(calls) == 3
    read(static, a)
    assert len(calls) == 3
    read(static, b)
    assert len(calls) == 4
    other_static = StaticDouble()
    read(other_static, b)
    assert len(calls) == 5
    now[0] = 300
    assert read(other_static, b)["sources"][0]["cached"] is True
    now[0] = 300.001
    assert not read(other_static, b)["sources"][0].get("cached", False)
    assert len(calls) == 6 and len(context._terrain_cache) <= 2


@pytest.mark.parametrize("invalid", [None, True, float("nan"), float("inf"), -1, 101, "50"])
def test_incomplete_or_invalid_soil_is_not_cached_as_success(invalid):
    calls = []

    class Evidence:
        def read(self, *_):
            calls.append(1)
            value = complete_evidence()
            value["ground_composition"]["composition"]["sand"] = invalid
            return value

    context = RouteContext(terrain_evidence_factory=lambda _: Evidence())
    static = StaticDouble()
    for _ in range(2):
        context._terrain_extra(static, {"latitude": 60.0, "longitude": 10.0}, "now")
    assert len(calls) == 2 and not context._terrain_cache


def test_unavailable_window_is_retryable_despite_complete_soil_values():
    calls = []

    class Evidence:
        def read(self, *_):
            calls.append(1)
            value = complete_evidence()
            value["sources"][1]["status"] = "unavailable"
            return value

    context = RouteContext(terrain_evidence_factory=lambda _: Evidence())
    static = StaticDouble()
    for _ in range(2):
        context._terrain_extra(static, {"latitude": 60.0, "longitude": 10.0}, "now")
    assert len(calls) == 2 and not context._terrain_cache


def test_two_admitted_requests_bound_workers_and_join_them_even_on_source_failure():
    entered, release = threading.Event(), threading.Event()
    gate = threading.Barrier(8, action=entered.set, timeout=3)
    lock, active, peak, calls = threading.Lock(), [0], [0], []

    def work(name, callback):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            calls.append(name)
        try:
            gate.wait()
            if name == "surface":
                raise RuntimeError("private source failure")
            assert release.wait(5)
            return callback()
        finally:
            with lock:
                active[0] -= 1

    class Evidence:
        def read(self, *_):
            return work("terrain", complete_evidence)

    class Weather(WeatherDouble):
        def forecast(self, *args):
            return work("weather", lambda: WeatherDouble().forecast(*args))

    class Canopy:
        def read_point(self, *_):
            return work("canopy", lambda: ({"percent": 73}, {"id": "clms-tree-cover-density", "status": "available"}))

    class Surface:
        def read_point(self, *_):
            return work("surface", lambda: None)

    app = FastAPI()
    app.state.static_sources = StaticDouble()
    app.state.live_weather = Weather()
    app.state.context_slots = threading.BoundedSemaphore(2)
    app.state.route_plan_store = RoutePlanStore()
    handle = app.state.route_plan_store.put("workspace-a", TerrainPlanner().plan(VALID))
    context = RouteContext(terrain_evidence_factory=lambda _: Evidence(), canopy_source=Canopy(), surface_observation=Surface())
    budgets = []
    from tests.runtime_routes.test_route_context import Session
    register_route_context_endpoints(app, lambda: Session(), lambda: Session(), budgets.append, context=context)

    def request(index):
        with TestClient(app) as client:
            return client.post("/api/v1/route-context", json={**selected(), "plan_id": handle, "section_index": index})

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(request, index) for index in (0, 1)]
        try:
            assert entered.wait(4), "two admitted requests failed to overlap their four lanes"
            denied = request(2)
            assert denied.status_code == 429
            assert budgets == ["workspace-a", "workspace-a"] and len(calls) == 8
            assert all(not future.done() for future in pending)
        finally:
            release.set()
        results = [future.result().json() for future in pending]
    assert peak[0] == 8 and active[0] == 0
    assert all(value["surface_observation"]["condition"] == "unknown" for value in results)
    assert all(value["ground_composition"]["composition"]["sand"] == 50 for value in results)
    assert "private source failure" not in str(results)
    assert not any(thread.name.startswith("groundsense-section") for thread in threading.enumerate())
