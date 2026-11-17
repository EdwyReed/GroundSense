"""Full application wiring and security gates for the terrain overview."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GROUNDSENSE_DATABASE_URL', f'sqlite:///{tmp_path}/profile-api.db')
    monkeypatch.setenv('GROUNDSENSE_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('GROUNDSENSE_PUBLIC_ORIGIN', 'https://testserver')
    from apps.api.main import create_app
    with TestClient(create_app(), base_url='https://testserver') as value:
        yield value


def test_profile_is_registered_before_generic_resource_fallback(client):
    assert any(getattr(route, 'path', '') == '/api/v1/terrain-profile' for route in client.app.routes)


def test_profile_requires_session_origin_csrf_and_a_bound_plan(client):
    payload = {'plan_id': 'a' * 32, 'route_id': 'transect-1'}
    assert client.post('/api/v1/terrain-profile', json=payload).status_code == 401
    boot = client.get('/api/v1/bootstrap').json()
    assert client.post('/api/v1/terrain-profile', json=payload).status_code == 403
    headers = {'Origin': 'https://testserver', 'X-CSRF-Token': boot['csrf_token']}
    assert client.post('/api/v1/terrain-profile', json=payload, headers=headers).status_code == 404
    assert client.post('/api/v1/terrain-profile', json={**payload, 'geometry': []}, headers=headers).status_code == 422
    assert client.post('/api/v1/terrain-profile', content=iter([b'x' * 8192, b'x']), headers={**headers, 'Content-Type': 'text/plain'}).status_code == 413
