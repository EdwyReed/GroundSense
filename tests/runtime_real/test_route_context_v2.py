"""Public-entrypoint gates for selected-section context; no provider reads."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GROUNDSENSE_DATABASE_URL', f'sqlite:///{tmp_path}/context-api.db')
    monkeypatch.setenv('GROUNDSENSE_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('GROUNDSENSE_PUBLIC_ORIGIN', 'https://testserver')
    from apps.api.main import create_app
    with TestClient(create_app(), base_url='https://testserver') as value:
        yield value


def test_context_endpoint_is_registered_not_generic_resource_fallback(client):
    assert any(getattr(route, 'path', '') == '/api/v1/route-context' for route in client.app.routes)


def test_context_requires_session_and_mutation_guards(client):
    payload = {'plan_id': 'a' * 32, 'route_id': 'route-1', 'section_index': 0}
    assert client.post('/api/v1/route-context', json=payload).status_code == 401
    boot = client.get('/api/v1/bootstrap').json()
    assert client.post('/api/v1/route-context', json=payload).status_code == 403
    headers = {'X-CSRF-Token': boot['csrf_token'], 'Origin': 'https://testserver'}
    assert client.post('/api/v1/route-context', json=payload, headers=headers).status_code == 404


@pytest.mark.parametrize('change', [{'plan_id': 'bad'}, {'section_index': True}, {'section_index': 32}])
def test_context_rejects_malformed_selection_before_source_reads(client, change):
    boot = client.get('/api/v1/bootstrap').json()
    headers = {'X-CSRF-Token': boot['csrf_token'], 'Origin': 'https://testserver'}
    payload = {'plan_id': 'a' * 32, 'route_id': 'route-1', 'section_index': 0, **change}
    assert client.post('/api/v1/route-context', json=payload, headers=headers).status_code == 422
