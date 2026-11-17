from __future__ import annotations

import threading
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from apps.api.route_planner import RoutePlanStore
from apps.api.static_sources import StaticSources
from apps.api.terrain_profile import TerrainProfile, register_terrain_profile_endpoints


class SurfaceProfileDouble:
    def __init__(self):
        self.calls = []

    def read_points(self, points, assessment_date):
        self.calls.append((points, assessment_date))
        samples = [{"chainage_m": row["chainage_m"], "requested_point": row["point"], "scl_class": 6, "condition": "water", "status": "available"} for row in points]
        return ({"status": "available", "basis": "sentinel2_l2a_scl_profile_points", "coverage": "discrete_points", "assessment_date": assessment_date, "retrieved_at": "2026-10-26T12:00:00Z", "observed_at": "2026-10-25T10:00:00Z", "scene_id": "scene", "scene_age_days": 1, "resolution_m": 20.0, "selection_scope": "bounded_catalogue_result", "samples": samples}, {"id": "sentinel-2-l2a", "status": "available", "qc": "available", "retrieved_at": "2026-10-26T12:00:00Z", "observed_at": "2026-10-25T10:00:00Z", "content_sha256": "sha256:x", "data": {"extraction_scope": "spaced_scene_classification_points"}})


class Session:
    workspace_id = "workspace-a"


def test_real_surface_adapter_receives_only_existing_profile_point_inputs(tmp_path):
    from tests.runtime_routes.test_surface_profile_contract import fixture
    surface, _, calls, _ = fixture(tmp_path)
    dem, cover = local_rasters(tmp_path)
    result = TerrainProfile(surface_profile=surface).read(terrain_plan(), {"plan_id": "a" * 32, "route_id": "transect-1"}, LocalStaticSources(tmp_path / "static-cache", dem, cover))
    assert len(calls) == 1
    summary = result["surface_observation_profile"]
    assert summary["scene_id"] == "scene"
    assert [row["requested_point"] for row in summary["samples"]] == [row["point"] for row in result["points"]]
    assert summary["source_content_sha256"] == result["sources"][-1]["content_sha256"]


class LocalStaticSources(StaticSources):
    def __init__(self, cache_dir: Path, dem: Path, cover: Path) -> None:
        super().__init__(cache_dir)
        self.dem, self.cover = str(dem), str(cover)

    def _urls_for_point(self, latitude, longitude):
        return {"terrain": self.dem, "worldcover": self.cover}


def local_rasters(tmp_path: Path) -> tuple[Path, Path]:
    transform = from_origin(10.0, 60.1, 0.1, 0.1)
    dem, cover = tmp_path / "dsm.tif", tmp_path / "cover.tif"
    for path, values, dtype, nodata in ((dem, [[-3, 0]], "float32", -9999), (cover, [[10, 255]], "uint8", 255)):
        with rasterio.open(path, "w", driver="GTiff", height=1, width=2, count=1, dtype=dtype, crs="EPSG:4326", transform=transform, nodata=nodata) as dataset:
            dataset.write(np.array(values, dtype=dtype), 1)
    return dem, cover


def terrain_plan() -> dict:
    return {"request": {"trip_date": "2026-10-26"}, "analysis_kind": "terrain_transect", "routes": [{"id": "transect-1", "geometry": {"type": "LineString", "coordinates": [[10.01, 60.05], [10.19, 60.05]]}}]}


def test_profile_reads_local_rasters_at_inclusive_endpoints_and_preserves_zero_negative_and_unknown(tmp_path):
    dem, cover = local_rasters(tmp_path)
    profile = TerrainProfile(clock=lambda: datetime(2026, 10, 26, tzinfo=UTC))

    result = profile.read(terrain_plan(), {"plan_id": "a" * 32, "route_id": "transect-1"}, LocalStaticSources(tmp_path / "cache", dem, cover))

    assert result["status"] == "partial"
    assert result["distance_m"] > 0
    assert result["sample_spacing_m"] <= 250
    assert result["points"][0]["point"] == {"longitude": 10.01, "latitude": 60.05}
    assert result["points"][-1]["point"] == {"longitude": 10.19, "latitude": 60.05}
    assert result["points"][0]["elevation_m"] == -3
    assert result["points"][-1]["elevation_m"] == 0
    assert result["points"][-1]["land_cover_class"] is None
    assert result["sources"][0]["extraction_scope"] == "transect_samples"
    assert result["sources"][0]["data"]["native_crs"] == "EPSG:4326"
    assert result["sources"][1]["data"]["static_reference_year"] == 2021
    assert result["sources"][1]["data"]["native_crs"] == "EPSG:4326"
    assert len(result["sources"]) == 3
    assert result["surface_observation_profile"]["status"] == "unavailable"
    assert result["surface_observation_profile"]["source_content_sha256"] is None
    assert result["sources"][-1]["data"]["extraction_scope"] == "spaced_scene_classification_points"
    assert all(source["extraction_scope"] == "transect_samples" for source in result["sources"][:2])
    trace = result["land_cover_trace"]
    assert trace["evidence_scope"] == "intersected_raster_cells"
    assert trace["coverage"] == "centerline_only"
    assert trace["segments"][-1]["class_code"] is None
    assert result["points"][-1]["land_cover_class"] is None


def test_endpoint_rejects_road_or_foreign_plan_before_budget_or_reads(tmp_path):
    dem, cover = local_rasters(tmp_path)
    app = FastAPI()
    app.state.static_sources = LocalStaticSources(tmp_path / "cache", dem, cover)
    app.state.context_slots = threading.BoundedSemaphore(1)
    app.state.route_plan_store = RoutePlanStore()
    budgets = []
    register_terrain_profile_endpoints(app, lambda: Session(), budgets.append)
    road_id = app.state.route_plan_store.put("workspace-a", {"request": {"trip_date": "2026-10-26"}, "routes": [{"id": "route-1"}]})
    client = TestClient(app)

    assert client.post("/api/v1/terrain-profile", json={"plan_id": road_id, "route_id": "route-1"}).status_code == 422
    assert client.post("/api/v1/terrain-profile", json={"plan_id": "b" * 32, "route_id": "transect-1"}).status_code == 404
    assert budgets == []


def test_profile_applies_native_offset_as_well_as_scale(tmp_path):
    dem, cover = local_rasters(tmp_path)
    with rasterio.open(dem, 'r+') as dataset:
        dataset.scales = (2.0,)
        dataset.offsets = (5.0,)
    result = TerrainProfile().read(terrain_plan(), {'plan_id': 'a' * 32, 'route_id': 'transect-1'}, LocalStaticSources(tmp_path / 'cache', dem, cover))
    assert result['points'][0]['elevation_m'] == -1
    assert result['points'][-1]['elevation_m'] == 5


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), float('-inf')])
def test_profile_nonfinite_cells_are_unknown_in_strict_json_and_saved_evidence(tmp_path, invalid):
    dem, cover = local_rasters(tmp_path)
    with rasterio.open(dem, 'r+') as dataset:
        dataset.write(np.array([[invalid, 0]], dtype='float32'), 1)
    result = TerrainProfile().read(terrain_plan(), {'plan_id': 'a' * 32, 'route_id': 'transect-1'}, LocalStaticSources(tmp_path / 'cache', dem, cover))
    assert result['points'][0]['elevation_m'] is None
    assert result['points'][-1]['elevation_m'] == 0
    json.dumps(result, allow_nan=False)
    receipts = list((tmp_path / 'cache' / 'evidence').glob('*.json'))
    assert receipts
    for receipt in receipts:
        json.dumps(json.loads(receipt.read_text()), allow_nan=False)


def test_partially_available_products_remain_partial_and_cacheable(tmp_path):
    dem, cover = local_rasters(tmp_path)
    with rasterio.open(dem, 'r+') as dataset:
        dataset.write(np.array([[-9999, 0]], dtype='float32'), 1)
    profile = TerrainProfile()
    result = profile.read(terrain_plan(), {'plan_id': 'a' * 32, 'route_id': 'transect-1'}, LocalStaticSources(tmp_path / 'cache', dem, cover))
    assert [source['status'] for source in result['sources']] == ['partial', 'partial', 'unavailable']
    assert result['status'] == 'partial'
    profile.remember('workspace-a', result)
    assert profile.cached('workspace-a', 'a' * 32, 'transect-1', '2026-10-26') == result


def test_sparse_endpoint_reads_its_native_pixel_instead_of_extending_the_previous_span(tmp_path):
    dem, cover = local_rasters(tmp_path)
    with rasterio.open(cover, 'w', driver='GTiff', height=1, width=2, count=1, dtype='uint8', crs='EPSG:4326', transform=from_origin(10, 60.125, .125, .125), nodata=255) as dataset:
        dataset.write(np.array([[10, 80]], dtype='uint8'), 1)
    plan = terrain_plan()
    plan['routes'][0]['geometry']['coordinates'] = [[10.01, 60.0625], [10.125, 60.0625]]
    result = TerrainProfile().read(plan, {'plan_id': 'a' * 32, 'route_id': 'transect-1'}, LocalStaticSources(tmp_path / 'cache', dem, cover))
    assert result['points'][-1]['land_cover_class'] == 80
    # Only the first pixel has positive-length intersection with the line.
    assert [row['class_code'] for row in result['land_cover_trace']['segments']] == [10]


def test_profile_appends_bounded_surface_summary_without_erasing_static_products(tmp_path):
    dem, cover = local_rasters(tmp_path)
    surface = SurfaceProfileDouble()
    result = TerrainProfile(surface_profile=surface).read(terrain_plan(), {'plan_id': 'a' * 32, 'route_id': 'transect-1'}, LocalStaticSources(tmp_path / 'cache', dem, cover))

    assert surface.calls and surface.calls[0][1] == '2026-10-26'
    assert result['surface_observation_profile']['samples'][0]['chainage_m'] == result['points'][0]['chainage_m']
    assert result['sources'][-1]['id'] == 'sentinel-2-l2a'
    assert result['points'][0]['elevation_m'] == -3

