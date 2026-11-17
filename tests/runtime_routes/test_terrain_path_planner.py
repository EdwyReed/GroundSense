"""Candidate path integration with local native rasters; no field access claims."""
from copy import deepcopy
import threading

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from apps.api.route_context import RouteContext
from apps.api.route_planner import RoutePlanStore
from apps.api.terrain_grid import TerrainGridSource
from apps.api.terrain_path_planner import TerrainPathPlanner, register_terrain_path_endpoints
from apps.api.terrain_profile import TerrainProfile
from tests.runtime_routes.test_terrain_grid import A, B, LocalSources


REQUEST = {'origin': A, 'destination': B, 'trip_date': '2026-10-26', 'vehicle': {'kind': 'truck_6x6', 'gross_mass_t': 20}}


def setup_planner(tmp_path, *, disconnected=False):
    cover = np.full((64, 64), 30, dtype='uint8')
    cover[30:41, 30] = 80
    if disconnected:
        cover[:, 30] = 80
    sources = LocalSources(tmp_path, cover)
    return TerrainPathPlanner(TerrainGridSource(sources, padding_m=30)), sources


def test_actual_area_search_routes_around_a_native_barrier_and_keeps_ab(tmp_path):
    planner, _ = setup_planner(tmp_path)
    result = planner.plan(REQUEST)
    assert result['status'] == 'ready'
    assert result['analysis_kind'] == 'terrain_candidate'
    assert result['vehicle_assessment'] == result['date_assessment'] == 'not_assessed'
    assert result['routing']['algorithm'] == 'a_star_8_connected'
    assert result['routing']['vehicle_used'] is False
    assert result['routing']['date_used'] is False
    route = result['routes'][0]
    assert route['geometry_kind'] == 'terrain_candidate'
    assert route['geometry']['coordinates'][0] == [A['longitude'], A['latitude']]
    assert route['geometry']['coordinates'][-1] == [B['longitude'], B['latitude']]
    assert len(route['geometry']['coordinates']) > 3
    assert route['planning']['grid_steps'] > 1
    assert route['planning']['cost'] > 0
    assert route['conditions']['status'] == 'not_assessed'
    assert len(result['routes']) <= 2


def test_disconnected_area_never_falls_back_to_a_straight_line(tmp_path):
    planner, _ = setup_planner(tmp_path, disconnected=True)
    result = planner.plan(REQUEST)
    assert result['status'] == 'no_route'
    assert result['routes'] == []
    assert result['routing']['search_status'] == 'no_path'


def test_failed_source_is_unavailable_not_no_route_or_open_land(tmp_path):
    planner, sources = setup_planner(tmp_path)
    sources.cover.unlink()
    result = planner.plan(REQUEST)
    assert result['status'] == 'unavailable'
    assert result['routes'] == []
    assert 'cover.tif' not in str(result)


def test_candidate_geometry_can_be_inspected_and_profiled_without_road_routing(tmp_path):
    planner, sources = setup_planner(tmp_path)
    plan = planner.plan(REQUEST)
    route = plan['routes'][0]
    selected = {'plan_id': 'a' * 32, 'route_id': route['id'], 'section_index': 0, 'sample_chainage_m': route['distance_m'] / 6}
    resolved, _ = RouteContext().resolve_selection(plan, selected)
    assert resolved['sample_point']
    profile = TerrainProfile().read(plan, {'plan_id': 'a' * 32, 'route_id': route['id']}, sources)
    assert len(profile['points']) >= 2
    assert profile['points'][0]['point'] == A
    assert profile['points'][-1]['point']['latitude'] == pytest.approx(B['latitude'])


def endpoint(tmp_path):
    planner, _ = setup_planner(tmp_path)
    app = FastAPI()
    app.state.context_slots = threading.BoundedSemaphore(2)
    app.state.route_plan_store = RoutePlanStore()
    class Session:
        workspace_id = 'workspace-a'
    def mutate(request: Request):
        if request.headers.get('x-fixture-auth') != 'yes':
            raise HTTPException(403)
        return Session()
    budgets = []
    register_terrain_path_endpoints(app, mutate, budgets.append, planner=planner)
    return app, TestClient(app), budgets


def test_endpoint_reuses_mutation_gate_and_workspace_owned_store(tmp_path):
    app, client, budgets = endpoint(tmp_path)
    assert client.post('/api/v1/terrain-path-plans', json=REQUEST).status_code == 403
    assert budgets == []
    response = client.post('/api/v1/terrain-path-plans', json=REQUEST, headers={'x-fixture-auth': 'yes'})
    assert response.status_code == 200
    body = response.json()
    assert app.state.route_plan_store.get('workspace-a', body['plan_id'])['routes'] == body['routes']
    assert app.state.route_plan_store.get('workspace-b', body['plan_id']) is None
    assert budgets == ['workspace-a']


@pytest.mark.parametrize('change', [{'origin': dict(A, latitude=80)}, {'vehicle': {'kind': 'truck_6x6', 'gross_mass_t': True}}, {'trip_date': 'bad'}])
def test_bad_request_rejects_before_budget(tmp_path, change):
    _, client, budgets = endpoint(tmp_path)
    response = client.post('/api/v1/terrain-path-plans', json={**REQUEST, **change}, headers={'x-fixture-auth': 'yes'})
    assert response.status_code == 422
    assert budgets == []


def test_body_and_admission_limits_reject_before_source_work(tmp_path):
    app, client, budgets = endpoint(tmp_path)
    assert client.post('/api/v1/terrain-path-plans', content=b'x' * 9000, headers={'x-fixture-auth': 'yes', 'Content-Type': 'text/plain'}).status_code == 413
    assert app.state.terrain_search_slots.acquire(blocking=False)
    try:
        assert client.post('/api/v1/terrain-path-plans', json=REQUEST, headers={'x-fixture-auth': 'yes'}).status_code == 429
        assert budgets == []
    finally:
        app.state.terrain_search_slots.release()
    assert client.post('/api/v1/terrain-path-plans', json=REQUEST, headers={'x-fixture-auth': 'yes'}).status_code == 200
