"""Integration checks for the original API shell; doubles are test-only, not live proof."""
from datetime import datetime, UTC
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GROUNDSENSE_DATABASE_URL', f'sqlite:///{tmp_path}/real.db')
    monkeypatch.setenv('GROUNDSENSE_DATA_DIR', str(tmp_path/'data'))
    from apps.api.main import create_app
    with TestClient(create_app(), base_url='https://testserver') as c:
        c.app.state.extra_sources = {}
        yield c

def boot(client):
    r=client.get('/api/v1/bootstrap');assert r.status_code==200
    return r.json(), {'Origin':'https://testserver','X-CSRF-Token':r.json()['csrf_token']}

def asset(client, headers):
    r=client.post('/api/v1/assets',headers=headers,json={'name':'Public test fixture point','type':'other','source_ref':'unit-test-only','geometry':{'type':'Point','coordinates':[10.75,59.91]}})
    assert r.status_code==201,r.text
    return r.json()

def test_public_csv_export_roundtrips_coordinates_including_negative_longitude(client):
    _, headers = boot(client)
    point = asset(client, headers)
    changed = client.patch('/api/v1/assets/'+point['id'],headers=headers,json={'expected_version':point['version'],'geometry':{'type':'Point','coordinates':[-10.78,59.66]}}).json()
    export = client.post('/api/v1/exports',headers=headers,json={'scope':'assets','format':'csv'}).json()
    content = client.get(export['download_url']).text
    with TestClient(client.app,base_url='https://testserver') as other:
        _, other_headers = boot(other)
        preview = other.post('/api/v1/imports',headers=other_headers,json={'resource':'assets','format':'csv','data':content}).json()
        assert preview['errors'] == []
        assert other.post('/api/v1/imports/'+preview['id']+'/commit',headers=other_headers).status_code == 200
        restored = other.get('/api/v1/assets/'+point['id']).json()
        assert restored['geometry'] == changed['geometry']
        assert restored['synthetic'] is False


def test_public_pdf_does_not_call_real_registry_records_synthetic(client,monkeypatch):
    from apps.api.main import canvas
    original = canvas.Canvas
    drawn = []
    class RecordedCanvas(original):
        def drawString(self,x,y,text,*args,**kwargs):
            drawn.append(text)
            return super().drawString(x,y,text,*args,**kwargs)
    monkeypatch.setattr(canvas,'Canvas',RecordedCanvas)
    _,headers = boot(client)
    asset(client,headers)
    result = client.post('/api/v1/exports',headers=headers,json={'scope':'assets','format':'pdf'}).json()
    assert client.get(result['download_url']).content.startswith(b'%PDF-')
    assert not any('синтетичн' in line.lower() or 'вигадан' in line.lower() for line in drawn)
    assert any('Прохідність не підтверджено' in line for line in drawn)


def test_default_original_bootstrap_contains_no_seed_and_canonical_source_identifiers(client):
    b,_=boot(client)
    assert b['workspace']['mode']=='public_data' and b['workspace']['synthetic'] is False
    assert b['assets']==b['segments']==b['observations']==[]
    assert b['soil']['composition'] is None
    assert b['context']['assessment_date']==datetime.now(UTC).date().isoformat()
    ids=[s['id']for s in b['sources']]
    assert {'copernicus-glo-30','sentinel-1-grd','sentinel-2-l2a','clms-swi-1km-v2'}<=set(ids)
    assert len(ids)==len(set(ids))

def test_existing_original_asset_registry_and_context_are_scoped_and_use_real_adapters(client):
    _,h=boot(client);a=asset(client,h)
    class StaticDouble:
        def read(self,lat,lon):
            assert (lat,lon)==(59.91,10.75)
            return {'soil':{'composition':{'sand':41,'silt':38,'clay':21},'depths':[]},'sources':[{'id':'soilgrids','status':'available'}]}
    class RemoteDouble:
        def read(self,lat,lon,day):
            assert day=='2024-01-15'
            return {'history':{'series':[]},'sources':[{'id':'era5-land','status':'available'}]}
    client.app.state.static_sources=StaticDouble();client.app.state.remote_sources=RemoteDouble()
    r=client.get('/api/v1/asset-context',params={'asset_id':a['id'],'assessment_date':'2024-01-15'})
    assert r.status_code==200,r.text
    assert r.json()['synthetic'] is False and r.json()['soil']['composition']['sand']==41
    assert r.json()['asset_id']==a['id']
    with TestClient(client.app,base_url='https://testserver') as other:
        boot(other)
        assert other.get('/api/v1/asset-context',params={'asset_id':a['id'],'assessment_date':'2024-01-15'}).status_code==404

def test_patch_cannot_reintroduce_synthetic_data_or_invalid_coordinates(client):
    _,h=boot(client);a=asset(client,h)
    r=client.patch('/api/v1/assets/'+a['id'],headers=h,json={'expected_version':a['version'],'synthetic':True,'condition':'less_adverse'})
    assert r.status_code==200,r.text
    assert r.json()['synthetic'] is False and r.json()['condition']=='unknown'
    r=client.patch('/api/v1/assets/'+a['id'],headers=h,json={'expected_version':r.json()['version'],'geometry':None})
    assert r.status_code==422


@pytest.mark.parametrize("endpoint", ["asset-context", "forecast", "analyses"])
def test_original_real_routes_share_the_public_source_quota(client, monkeypatch, endpoint):
    from types import SimpleNamespace
    monkeypatch.setattr("apps.api.main.threading.Timer", lambda *a, **kw: SimpleNamespace(start=lambda: None))
    _, h = boot(client)
    a = asset(client, h)
    client.app.state.static_sources = SimpleNamespace(read=lambda *a: {})
    client.app.state.remote_sources = SimpleNamespace(read=lambda *a: {})
    client.app.state.live_weather = SimpleNamespace(forecast=lambda *a: {"source": {}, "series": []})
    statuses = []
    selection = {"asset_id": a["id"], "assessment_date": "2026-10-25", "gross_mass_t": 20}
    for index in range(13):
        response = client.post('/api/v1/analyses', headers={**h, 'Idempotency-Key': f'quota-{index}'}, json=selection) if endpoint == 'analyses' else client.get('/api/v1/'+endpoint, params=selection)
        statuses.append(response.status_code)
    assert statuses[:12] == [202 if endpoint == 'analyses' else 200] * 12
    assert statuses[-1] == 429


def test_context_merges_dedicated_integrations_by_canonical_id(client):
    from types import SimpleNamespace
    _, headers = boot(client)
    point = asset(client, headers)
    client.app.state.static_sources = SimpleNamespace(read=lambda *a: {})
    client.app.state.remote_sources = SimpleNamespace(read=lambda *a: {'sources': [{'id':'clms-swi-1km-v2','status':'partial'}]})
    client.app.state.extra_sources = {
        'clms': SimpleNamespace(read=lambda *a: {'soil_moisture': {'swi': {'value': 42, 'unit':'%'}}, 'sources': [{'id':'clms-swi-1km-v2','status':'available','data':{'value':42}}]}),
        'osm': SimpleNamespace(read=lambda *a: {'ways': [{'osm_id':123}], 'source': {'id':'openstreetmap','status':'available'}}),
        'context': SimpleNamespace(read=lambda *a: {'context':{'hwsd_v2':{'map_unit_id':None},'esdac_ukraine_soil_map':{'point_soil_class':None}},'sources':[{'id':'hwsd-v2','status':'partial'}]}),
        'hwsd': SimpleNamespace(read=lambda *a: {'context':{'hwsd_v2':{'map_unit_id':10128,'attributes':None}},'sources':[{'id':'hwsd-v2','status':'partial','data':{'extraction':'rasterio_vsizip_bil_point'}}]}),
    }
    response = client.get('/api/v1/asset-context', params={'asset_id':point['id'],'assessment_date':'2026-10-25'})
    assert response.status_code == 200
    result = response.json()
    assert result['soil_moisture']['swi']['value'] == 42
    assert result['osm']['ways'][0]['osm_id'] == 123
    assert result['historical_context']['hwsd_v2']['map_unit_id'] == 10128
    assert result['historical_context']['esdac_ukraine_soil_map']['point_soil_class'] is None
    assert [s['id'] for s in result['sources']].count('hwsd-v2') == 1
    assert [s['id'] for s in result['sources']].count('clms-swi-1km-v2') == 1
    assert next(s for s in result['sources'] if s['id']=='clms-swi-1km-v2')['status'] == 'available'


def test_one_broken_adapter_does_not_destroy_other_source_results(client):
    from types import SimpleNamespace
    _, headers = boot(client)
    point = asset(client, headers)
    def broken(*args):
        raise OSError('provider fixture failure')
    client.app.state.static_sources = SimpleNamespace(read=broken)
    client.app.state.remote_sources = SimpleNamespace(read=lambda *a: {'sources':[{'id':'era5-land','status':'available'}]})
    response = client.get('/api/v1/asset-context', params={'asset_id':point['id'],'assessment_date':'2026-10-25'})
    assert response.status_code == 200
    result = response.json()
    assert next(s for s in result['sources'] if s['id']=='era5-land')['status'] == 'available'
    assert next(s for s in result['sources'] if s['id']=='soilgrids')['status'] == 'unavailable'
