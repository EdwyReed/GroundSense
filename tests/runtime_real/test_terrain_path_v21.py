"""Full application guards and owned path/profile handles; local native rasters."""
import pytest
from fastapi.testclient import TestClient

from tests.runtime_routes.test_terrain_path_planner import REQUEST, setup_planner


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GROUNDSENSE_DATABASE_URL', f'sqlite:///{tmp_path}/paths.db')
    monkeypatch.setenv('GROUNDSENSE_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('GROUNDSENSE_PUBLIC_ORIGIN', 'https://testserver')
    from apps.api.main import create_app
    from apps.api.route_planner import RoutePlanner
    def forbidden(*args, **kwargs):
        raise AssertionError('Off-road candidate search called road routing')
    monkeypatch.setattr(RoutePlanner, '_get_json', forbidden)
    app = create_app()
    planner, sources = setup_planner(tmp_path)
    # Keep the registered adapter instance: its closure is the actual endpoint.
    app.state.terrain_path_planner.grids = planner.grids
    app.state.static_sources = sources
    with TestClient(app, base_url='https://testserver') as value:
        yield value


def headers(client):
    boot = client.get('/api/v1/bootstrap').json()
    return {'Origin': 'https://testserver', 'X-CSRF-Token': boot['csrf_token']}


def test_real_origin_csrf_and_streamed_size_guards(client):
    assert client.post('/api/v1/terrain-path-plans', json=REQUEST).status_code == 401
    good = headers(client)
    assert client.post('/api/v1/terrain-path-plans', json=REQUEST).status_code == 403
    assert client.post('/api/v1/terrain-path-plans', json=REQUEST, headers={**good, 'Origin': 'https://foreign.invalid'}).status_code == 403
    assert client.post('/api/v1/terrain-path-plans', json=REQUEST, headers={**good, 'X-CSRF-Token': 'not-the-session-token'}).status_code == 403
    assert client.post('/api/v1/terrain-path-plans', content=iter([b'x' * 8192, b'x']), headers={**good, 'Content-Type': 'text/plain'}).status_code == 413
    assert client.post('/api/v1/terrain-path-plans', json=REQUEST, headers=good).status_code == 200


def test_owned_candidate_handle_profiles_bent_geometry_and_foreign_workspace_cannot_reuse_it(client):
    good = headers(client)
    result = client.post('/api/v1/terrain-path-plans', json=REQUEST, headers=good)
    assert result.status_code == 200
    plan = result.json()
    route = plan['routes'][0]
    assert len(route['geometry']['coordinates']) > 3
    selected = {'plan_id': plan['plan_id'], 'route_id': route['id']}
    profile = client.post('/api/v1/terrain-profile', json=selected, headers=good)
    assert profile.status_code == 200
    assert profile.json()['route_id'] == route['id']
    assert profile.json()['distance_m'] == pytest.approx(route['distance_m'])
    assert profile.json()['points'][0]['point'] == REQUEST['origin']
    from apps.api.route_context import RouteContext
    chainage = route['distance_m'] / 2
    section_index = next(index for index, span in enumerate(route['section_spans']) if span['from_m'] <= chainage <= span['to_m'])
    selection = {**selected, 'section_index': section_index, 'sample_chainage_m': chainage}
    resolved, _ = RouteContext().resolve_selection(plan, selection)
    assert resolved['sample_point'] != REQUEST['origin']
    client.cookies.clear()
    foreign = headers(client)
    assert client.post('/api/v1/terrain-profile', json=selected, headers=foreign).status_code == 404
    assert client.post('/api/v1/route-context', json=selection, headers=foreign).status_code == 404
