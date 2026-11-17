"""Exercise the V7 contract through the actual guarded application, using local rasters."""
from __future__ import annotations

import math

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from apps.api.static_sources import StaticSources


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GROUNDSENSE_DATABASE_URL', f'sqlite:///{tmp_path}/trace-api.db')
    monkeypatch.setenv('GROUNDSENSE_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('GROUNDSENSE_PUBLIC_ORIGIN', 'https://testserver')
    from apps.api.main import create_app
    path = tmp_path / 'narrow-water.tif'
    cells = np.full((4, 60), 10, dtype='uint8')
    cells[:, 17] = 80
    with rasterio.open(path, 'w', driver='GTiff', height=4, width=60, count=1, dtype='uint8', crs='EPSG:4326', transform=from_origin(10, 60, 1 / 12000, 1 / 12000), nodata=0) as dataset:
        dataset.write(cells, 1)

    class LocalSources(StaticSources):
        def _urls_for_point(self, latitude, longitude):
            return {'worldcover': str(path)}

    app = create_app()
    app.state.static_sources = LocalSources(tmp_path / 'evidence-cache')
    with TestClient(app, base_url='https://testserver') as value:
        yield value, path


def test_same_guarded_profile_exposes_narrow_water_between_sparse_points_and_caches_it(client):
    api, path = client
    boot = api.get('/api/v1/bootstrap').json()
    headers = {'Origin': 'https://testserver', 'X-CSRF-Token': boot['csrf_token']}
    request = {'origin': {'longitude': 10.00003, 'latitude': 59.99995}, 'destination': {'longitude': 10.00497, 'latitude': 59.99995}, 'trip_date': '2026-10-26', 'vehicle': {'kind': 'truck_6x6', 'gross_mass_t': 20}}
    plan = api.post('/api/v1/terrain-plans', headers=headers, json=request)
    assert plan.status_code == 200
    selection = {'plan_id': plan.json()['plan_id'], 'route_id': 'transect-1'}
    response = api.post('/api/v1/terrain-profile', headers=headers, json=selection)
    assert response.status_code == 200
    data = response.json()
    assert all(row['land_cover_class'] == 10 for row in data['points'])
    trace = data['land_cover_trace']
    assert trace['status'] == 'available'
    assert trace['evidence_scope'] == 'intersected_raster_cells' and trace['coverage'] == 'centerline_only'
    assert trace['reference_year'] == 2021
    assert [row['class_code'] for row in trace['segments']] == [10, 80, 10]
    assert trace['unknown_m'] == 0
    assert math.isclose(trace['known_m'], data['distance_m'], abs_tol=1e-6)
    assert trace['segments'][0]['start_m'] == 0
    assert math.isclose(trace['segments'][-1]['end_m'], data['distance_m'], abs_tol=1e-6)
    for left, right in zip(trace['segments'], trace['segments'][1:]):
        assert math.isclose(left['end_m'], right['start_m'], abs_tol=1e-6)
        assert left['geometry']['coordinates'][-1] == right['geometry']['coordinates'][0]
    assert trace['cell_count'] > len(data['points'])
    assert trace['tile_attempts'] == 1
    assert trace['sources'][0]['content_sha256'].startswith('sha256:')
    # Removing the source proves repeat readback uses the response cache.
    path.unlink()
    assert api.post('/api/v1/terrain-profile', headers=headers, json=selection).json() == data
    assert api.post('/api/v1/terrain-profile', headers={'Origin': 'https://testserver'}, json=selection).status_code == 403
    assert api.post('/api/v1/terrain-profile', headers=headers, json={**selection, 'route_id': 'foreign'}).status_code == 404
    assert api.get('/api/v1/bootstrap').json()['assets'] == boot['assets']
