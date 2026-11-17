"""Real-mode integration tests. Provider doubles below are test-only, never runtime data."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GROUNDSENSE_DATABASE_URL', f'sqlite:///{tmp_path}/live.db')
    monkeypatch.setenv('GROUNDSENSE_DATA_DIR', str(tmp_path/'data'))
    from apps.api.main import create_app
    with TestClient(create_app(data_mode='synthetic'), base_url='https://testserver') as c:
        yield c


def live(client):
    r=client.get('/api/v1/live/bootstrap')
    assert r.status_code==200
    b=r.json()
    return b, {'Origin':'https://testserver','X-CSRF-Token':b['csrf_token']}


def point(**extra):
    return {'name':'Тестова точка без твердження про скважину','latitude':59.91,'longitude':10.75,'source_ref':'test:unit-fixture',**extra}


def test_live_bootstrap_has_no_invented_assets_even_after_opening_test_stand(client):
    b,h=live(client)
    assert b['workspace']['mode']=='public_data' and b['workspace']['synthetic'] is False
    assert b['assets']==[]
    assert 'HttpOnly' in client.get('/api/v1/bootstrap').headers.get('set-cookie','') or client.cookies.get('__Host-gs_session')
    assert len(client.get('/api/v1/bootstrap').json()['assets'])==12
    assert client.get('/api/v1/live/bootstrap').json()['assets']==[]
    r=client.post('/api/v1/live/assets',json=point(),headers=h)
    assert r.status_code==201
    asset=r.json()
    assert asset['synthetic'] is False and asset['data_origin']=='user_supplied' and asset['condition']=='unknown'
    assert asset['geometry']=={'type':'Point','coordinates':[10.75,59.91]}
    assert client.get('/api/v1/live/assets/'+asset['id']).json()==asset
    assert len(client.get('/api/v1/live/bootstrap').json()['assets'])==1
    assert all(x['id']!=asset['id'] for x in client.get('/api/v1/bootstrap').json()['assets'])


def test_opening_synthetic_after_saving_real_asset_still_initialises_test_registry(client):
    _,h=live(client)
    assert client.post('/api/v1/live/assets',json=point(),headers=h).status_code==201
    assert len(client.get('/api/v1/bootstrap').json()['assets'])==12


@pytest.mark.parametrize('changes',[{'latitude':True},{'latitude':91},{'longitude':181},{'longitude':'NaN'},{'latitude':None},{'name':''},{'source_ref':''}])
def test_invalid_real_point_does_not_get_default_coordinates(client,changes):
    _,h=live(client)
    assert client.post('/api/v1/live/assets',json=point(**changes),headers=h).status_code==422
    assert client.get('/api/v1/live/bootstrap').json()['assets']==[]


def test_real_asset_requires_csrf_and_is_isolated(client):
    _,h=live(client)
    assert client.post('/api/v1/live/assets',json=point()).status_code==403
    a=client.post('/api/v1/live/assets',json=point(),headers=h).json()
    with TestClient(client.app,base_url='https://testserver') as other:
        live(other)
        assert other.get('/api/v1/live/assets/'+a['id']).status_code==404
        assert other.get('/api/v1/live/bootstrap').json()['assets']==[]


def test_real_point_import_is_atomic_and_has_explicit_provenance(client):
    _,h=live(client)
    raw='name,latitude,longitude,source_ref\nТочка,59.91,10.75,test:fixture\nНевірна,999,10.75,test:fixture\n'
    assert client.post('/api/v1/live/assets/import',json={'format':'csv','data':raw},headers=h).status_code==422
    assert client.get('/api/v1/live/bootstrap').json()['assets']==[]
    r=client.post('/api/v1/live/assets/import',json={'format':'csv','data':'name,latitude,longitude,source_ref\nТочка,59.91,10.75,test:fixture\n'},headers=h)
    assert r.status_code==201 and r.json()['imported']==1
    assert client.get('/api/v1/live/bootstrap').json()['assets'][0]['source_ref']=='test:fixture'
    features={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'name':'Публічна точка','source_ref':'test:geojson'},'geometry':{'type':'Point','coordinates':[10.76,59.92]}}]}
    r=client.post('/api/v1/live/assets/import',json={'format':'geojson','data':json.dumps(features)},headers=h)
    assert r.status_code==201 and r.json()['items'][0]['longitude']==10.76


def test_real_weather_snapshot_is_read_back_with_workspace_acl(client,tmp_path):
    raw=b'{"fixture":true,"not_live_data":true}'
    digest=hashlib.sha256(raw).hexdigest()
    path=tmp_path/'provider.json';path.write_bytes(raw)
    class ProviderDouble:
        def forecast(self,latitude,longitude,assessment_date=None):
            return {'mode':'live','synthetic':False,'source':{'id':'open-meteo-icon-global','content_sha256':'sha256:'+digest,'retrieved_at':'2026-10-25T00:00:00Z'},'series':[]}
        def snapshot_path(self,ident):
            assert ident==digest
            return path
    client.app.state.live_weather=ProviderDouble()
    live(client)
    r=client.get('/api/v1/live/weather',params={'latitude':59.91,'longitude':10.75,'assessment_date':'2026-10-25'})
    assert r.status_code==200 and r.json()['synthetic'] is False
    downloaded=client.get('/api/v1/live/weather/snapshots/'+digest)
    assert downloaded.status_code==200 and downloaded.content==raw
    with TestClient(client.app,base_url='https://testserver') as other:
        live(other)
        assert other.get('/api/v1/live/weather/snapshots/'+digest).status_code==404
