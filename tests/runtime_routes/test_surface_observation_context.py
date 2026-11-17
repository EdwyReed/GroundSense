from __future__ import annotations

from apps.api.route_context import RouteContext
from apps.api.terrain_planner import TerrainPlanner
from tests.runtime_routes.test_route_context import StaticDouble, VALID, WeatherDouble


class SurfaceDouble:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def read_point(self, latitude, longitude, assessment_date):
        self.calls.append((latitude, longitude, assessment_date))
        if self.fail:
            raise RuntimeError("private provider failure")
        return ({"status": "available", "basis": "sentinel2_l2a_scl_point", "assessment_date": assessment_date, "requested_point": {"latitude": latitude, "longitude": longitude}, "observed_at": "2026-10-25T10:00:00Z", "retrieved_at": "2026-10-26T12:00:00Z", "scene_age_days": 1, "scene_id": "scene", "scl_class": 6, "condition": "water", "resolution_m": 20.0, "selection_scope": "bounded_catalogue_result"}, {"id": "sentinel-2-l2a", "status": "available", "qc": "available", "retrieved_at": "2026-10-26T12:00:00Z", "observed_at": "2026-10-25T10:00:00Z", "content_sha256": "sha256:x", "data": {"extraction_scope": "scene_classification_point"}})


def test_offroad_context_adds_surface_observation_at_server_selected_point_only():
    surface = SurfaceDouble()
    context = RouteContext(surface_observation=surface, terrain_evidence_factory=lambda _: None)
    plan = TerrainPlanner().plan(VALID)
    selected = {"plan_id": "a" * 32, "route_id": "transect-1", "section_index": 1}

    result = context.build(plan, selected, StaticDouble(), WeatherDouble())

    point = result["sections"][1]["point"]
    assert result["surface_observation"]["requested_point"] == point
    assert surface.calls == [(point["latitude"], point["longitude"], VALID["trip_date"])]
    source = next(row for row in result["sources"] if row["id"] == "sentinel-2-l2a")
    assert source["extraction_scope"] == "scene_classification_point"
    assert "dry" not in str(result) and "proceed" not in str(result)


def test_road_context_never_queries_surface_observation():
    surface = SurfaceDouble()
    context = RouteContext(surface_observation=surface)
    from tests.runtime_routes.test_route_context import planner
    result = context.build(planner().plan(VALID), {"plan_id": "a" * 32, "route_id": "route-1", "section_index": 0}, StaticDouble(), WeatherDouble())
    assert "surface_observation" not in result and surface.calls == []


def test_surface_failure_is_explicit_unknown_and_preserves_other_context():
    context = RouteContext(surface_observation=SurfaceDouble(fail=True), terrain_evidence_factory=lambda _: None)
    result = context.build(TerrainPlanner().plan(VALID), {"plan_id": "a" * 32, "route_id": "transect-1", "section_index": 0}, StaticDouble(), WeatherDouble())
    assert result["surface_observation"] == {"status": "unavailable", "basis": "sentinel2_l2a_scl_point", "condition": "unknown"}
    assert result["terrain"]["elevation_m"] == 241 and result["weather"]["assessment_date"] == VALID["trip_date"]
    assert "private provider failure" not in str(result)
