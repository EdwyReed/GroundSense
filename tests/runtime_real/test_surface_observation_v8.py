"""V8 through the real CSRF/workspace-bound app with an actual local SCL raster."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json

import httpx
import numpy as np
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform


def test_native_cloud_observation_is_server_bound_cached_and_guarded(tmp_path, monkeypatch):
    from apps.api.surface_observation import SurfaceObservation
    from apps.api.tree_cover_density import TreeCoverDensity
    monkeypatch.setenv('GROUNDSENSE_DATABASE_URL', f'sqlite:///{tmp_path}/surface-api.db')
    monkeypatch.setenv('GROUNDSENSE_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('GROUNDSENSE_PUBLIC_ORIGIN', 'https://testserver')
    from apps.api.main import create_app

    cloud = tmp_path / 'native-cloud.tif'
    x, y = transform('EPSG:4326', 'EPSG:32632', [10.0025], [59.99995])
    with rasterio.open(cloud, 'w', driver='GTiff', height=40, width=40, count=1, dtype='uint8', crs='EPSG:32632',
                       transform=from_origin(x[0] - 400, y[0] + 400, 20, 20), nodata=0) as dataset:
        dataset.write(np.full((40, 40), 8, dtype='uint8'), 1)
    url = 'https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/32/V/NM/2026/10/S2A_32VNM_20261025_0_L2A/SCL.tif'
    calls = []

    def catalogue(request):
        assert str(request.url) == 'https://earth-search.aws.element84.com/v1/search'
        payload = json.loads(request.content)
        assert payload['collections'] == ['sentinel-2-l2a'] and payload['limit'] <= 12
        calls.append(payload)
        return httpx.Response(200, json={'features': [{'id': 'S2A_32VNM_20261025_0_L2A', 'collection': 'sentinel-2-l2a',
            'properties': {'datetime': '2026-10-25T10:44:25Z'},
            'assets': {'scl': {'href': url, 'raster:bands': [{'nodata': 0, 'scale': 1, 'offset': 0}]}}}]})

    native_open = rasterio.open
    opens = []

    def local_open(path, *args, **kwargs):
        assert path == url
        opens.append(path)
        return native_open(cloud, *args, **kwargs)

    # All remote catalogue/COG operations are directed to deterministic local evidence.
    sampler = SurfaceObservation(tmp_path / 'surface', transport=httpx.MockTransport(catalogue), clock=lambda: datetime(2026, 10, 26, 12, tzinfo=UTC))
    native_read = SurfaceObservation.read_point
    source_calls = []

    def selected_read(self, latitude, longitude, assessment_date):
        source_calls.append((latitude, longitude, assessment_date))
        return native_read(sampler, latitude, longitude, assessment_date)

    monkeypatch.setattr(rasterio, 'open', local_open)
    monkeypatch.setattr(SurfaceObservation, 'read_point', selected_read)
    monkeypatch.setattr(TreeCoverDensity, 'read_point', lambda *_: ({'percent': 0, 'reference_year': 2018, 'resolution_m': 10}, {'id': 'clms-tree-cover-density', 'status': 'available'}))

    class Static:
        def _urls_for_point(self, *_):
            return {'terrain': 'local-terrain', 'worldcover': 'local-cover'}

        def _terrain(self, *_):
            return {'elevation_m': 10, 'surface_kind': 'DSM', 'support_m': 30}, {'id': 'copernicus-glo-30', 'status': 'available'}

        def _land_cover(self, *_):
            return {'class': 10, 'label': 'tree_cover', 'support_m': 10, 'reference_year': 2021}, {'id': 'esa-worldcover', 'status': 'available'}

    class Evidence:
        def read(self, *_):
            return {'sources': [], 'ground_composition': {'status': 'unknown'}}

    class Weather:
        def forecast(self, latitude, longitude, trip_date):
            return {'assessment_date': trip_date, 'source': {'id': 'open-meteo-icon-global'}, 'units': {}, 'series': [], 'qc': {'status': 'unavailable'}}

    app = create_app()
    app.state.static_sources = Static()
    app.state.live_weather = Weather()
    app.state.route_context._terrain_evidence_factory = lambda _: Evidence()
    with TestClient(app, base_url='https://testserver') as api:
        boot = api.get('/api/v1/bootstrap').json()
        headers = {'Origin': 'https://testserver', 'X-CSRF-Token': boot['csrf_token']}
        trip = {'origin': {'longitude': 10.00003, 'latitude': 59.99995}, 'destination': {'longitude': 10.00497, 'latitude': 59.99995},
                'trip_date': '2026-10-26', 'vehicle': {'kind': 'truck_6x6', 'gross_mass_t': 20}}
        created = api.post('/api/v1/terrain-plans', headers=headers, json=trip)
        assert created.status_code == 200
        selection = {'plan_id': created.json()['plan_id'], 'route_id': 'transect-1', 'section_index': 0}
        assert api.post('/api/v1/route-context', json=selection).status_code == 403
        assert source_calls == calls == opens == []
        response = api.post('/api/v1/route-context', headers=headers, json=selection)
        assert response.status_code == 200
        data = response.json()
        json.dumps(data, allow_nan=False)
        observation = data['surface_observation']
        point = data['sections'][0]['point']
        assert observation['requested_point'] == point
        assert source_calls == [(point['latitude'], point['longitude'], trip['trip_date'])]
        assert len(calls) == len(opens) == 1
        assert observation['scl_class'] == 8 and observation['condition'] == 'cloud'
        assert observation['status'] == 'partial' and observation['resolution_m'] == 20
        assert observation['observed_at'] == '2026-10-25T10:44:25Z'
        source = next(row for row in data['sources'] if row['id'] == 'sentinel-2-l2a')
        assert source['extraction_scope'] == 'scene_classification_point'
        digest = source['content_sha256'].removeprefix('sha256:')
        assert hashlib.sha256((sampler.evidence_dir / f'{digest}.json').read_bytes()).hexdigest() == digest
        assert data['terrain']['elevation_m'] == 10
        assert data['canopy_cover']['percent'] == 0
        cloud.unlink()
        assert api.post('/api/v1/route-context', headers=headers, json=selection).json() == data
        assert len(source_calls) == len(calls) == len(opens) == 1
        assert api.post('/api/v1/route-context', headers=headers, json={**selection, 'section_index': True}).status_code == 422
        oversized = api.post('/api/v1/route-context', headers={**headers, 'Content-Type': 'text/plain'}, content=iter([b'x' * 8192, b'x']))
        assert oversized.status_code == 413
        with TestClient(app, base_url='https://testserver') as other:
            foreign = other.get('/api/v1/bootstrap').json()
            denied = other.post('/api/v1/route-context', headers={'Origin': 'https://testserver', 'X-CSRF-Token': foreign['csrf_token']}, json=selection)
            assert denied.status_code == 404
        assert len(source_calls) == len(calls) == len(opens) == 1
        assert api.get('/api/v1/bootstrap').json()['assets'] == boot['assets']
