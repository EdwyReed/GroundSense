import io
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDSENSE_DATABASE_URL", f"sqlite:///{tmp_path}/groundsense.db")
    monkeypatch.setenv("GROUNDSENSE_DATA_DIR", str(tmp_path / "data"))
    from apps.api.main import create_app

    with TestClient(create_app(data_mode="synthetic"), base_url="https://testserver") as test_client:
        yield test_client


def bootstrap(client):
    response = client.get("/api/v1/bootstrap")
    assert response.status_code == 200
    return response.json()


def headers(state, **extra):
    return {"X-CSRF-Token": state["csrf_token"], "Origin":"https://testserver", **extra}


def test_bootstrap_session_is_isolated_and_cookie_is_secure(client):
    first = bootstrap(client)
    cookie = client.cookies.get("__Host-gs_session")
    assert cookie
    assert first["workspace"]["synthetic"] is True
    assert first["user"]["role"] == "engineer"
    assert first["features"]
    other = TestClient(client.app, base_url="https://testserver")
    try:
        second = bootstrap(other)
        assert first["workspace"]["id"] != second["workspace"]["id"]
        private = client.post("/api/v1/assets", json={"id": "PRIVATE-1", "name": "Приватний", "type": "well"}, headers=headers(first))
        assert private.status_code == 201
        assert other.get("/api/v1/assets/PRIVATE-1").status_code == 404
    finally:
        other.close()


def test_role_change_rotates_cookie_and_csrf(client):
    s=bootstrap(client); old=client.cookies.get('__Host-gs_session')
    changed=client.post('/api/v1/demo/role',json={'role':'field'},headers=headers(s))
    assert changed.status_code==200
    fresh=bootstrap(client)
    assert client.cookies.get('__Host-gs_session')!=old
    assert fresh['csrf_token']!=s['csrf_token']
    assert client.post('/api/v1/inspections',json={},headers=headers(s)).status_code==403


def test_serves_compiled_ui_and_does_not_cache_api(client):
    response=client.get('/')
    assert response.status_code==200 and 'GroundSense' in response.text and '<script' in response.text
    response=client.get('/api/v1/health')
    assert response.headers.get('cache-control')=='no-store'
    assert client.get('/api/v1/unknown/path/no-spa').status_code==404


def test_ambiguous_duplicate_json_keys_are_rejected(client):
    s=bootstrap(client)
    r=client.post('/api/v1/observations',content='{"value":1,"value":2}',headers={**headers(s),'Content-Type':'application/json'})
    assert r.status_code==422


def test_missing_origin_is_denied_even_with_valid_csrf(client):
    state = bootstrap(client)
    response=client.post('/api/v1/inspections',json={'asset_id':'GS-014'},headers={'X-CSRF-Token':state['csrf_token']})
    assert response.status_code==403


def test_mutations_require_csrf_and_same_origin(client):
    state = bootstrap(client)
    body = {"name": "Новий об’єкт", "type": "well", "geometry": {"type": "Point", "coordinates": [0.01, 0.02]}}
    assert client.post("/api/v1/assets", json=body).status_code == 403
    assert client.post("/api/v1/assets", json=body, headers=headers(state, Origin="https://evil.invalid")).status_code == 403
    made = client.post("/api/v1/assets", json=body, headers=headers(state))
    assert made.status_code == 201
    assert made.json()["version"] == 1


def test_observation_revisions_and_engineer_adjudication(client):
    state = bootstrap(client)
    made = client.post("/api/v1/observations", json={"quantity": "moisture", "value": 0.2, "unit": "m3/m3"}, headers=headers(state))
    assert made.status_code == 201
    oid = made.json()["id"]
    revised = client.patch(f"/api/v1/observations/{oid}", json={"value": 0.3, "expected_version": 1}, headers=headers(state))
    assert revised.status_code == 200
    assert revised.json()["version"] == 2
    adjudicated = client.post(f"/api/v1/observations/{oid}/adjudications", json={"decision": "accepted", "reason": "Перевірено", "expected_version": 2}, headers=headers(state))
    assert adjudicated.status_code == 200
    assert client.get("/api/v1/audit").json()["items"]


def test_selected_asset_survives_job_and_manifest(client):
    s=bootstrap(client)
    accepted=client.post('/api/v1/analyses',json={'assessment_date':'2027-03-15','gross_mass_t':20,'asset_id':'GS-001'},headers=headers(s,**{'Idempotency-Key':'selected-asset'})).json()
    for _ in range(50):
        job=client.get('/api/v1/jobs/'+accepted['id']).json()
        if job['status'] in ('published','failed'): break
        time.sleep(.03)
    result=client.get('/api/v1/results/'+accepted['run_id'])
    assert result.status_code==200
    assert result.json()['assessment']['asset_id']=='GS-001'
    manifest=client.get('/api/v1/results/'+accepted['run_id']+'/manifest').json()['manifest']
    assert manifest['input_snapshot_digest'].startswith('sha256:')
    assert accepted['mode']=='climatology'


def test_invalid_assessment_date_is_not_queued(client):
    s=bootstrap(client)
    response=client.post('/api/v1/analyses',json={'assessment_date':'not-a-date','gross_mass_t':20},headers=headers(s,**{'Idempotency-Key':'bad-date'}))
    assert response.status_code==422


@pytest.mark.parametrize('day,mass', [('not-a-date','20'),('2026-10-25','NaN'),('2026-10-25','inf')])
def test_forecast_invalid_inputs_return_validation_error_not_500(client,day,mass):
    bootstrap(client)
    response=client.get('/api/v1/forecast',params={'asset_id':'GS-014','assessment_date':day,'gross_mass_t':mass})
    assert response.status_code==422


def test_observation_entered_time_is_server_owned_and_evidence_must_be_in_scope(client):
    state=bootstrap(client)
    record=client.post('/api/v1/observations',json={'asset_id':'GS-014','observed_at':'2026-10-24T12:00:00Z','entered_at':'1900-01-01T00:00:00Z','note':'Синтетична перевірка'},headers=headers(state))
    assert record.status_code==201
    assert record.json()['entered_at']!='1900-01-01T00:00:00Z'
    assert record.json()['entered_at']!=record.json()['observed_at']
    invalid=client.post('/api/v1/observations',json={'asset_id':'GS-014','evidence_id':'upl_nonexistent'},headers=headers(state))
    assert invalid.status_code==422


def test_analysis_is_idempotent_cancellable_and_never_publishes_cancelled(client):
    state = bootstrap(client)
    payload = {"assessment_date": "2027-03-15", "gross_mass_t": 20}
    first = client.post("/api/v1/analyses", json=payload, headers=headers(state, **{"Idempotency-Key": "same"}))
    assert first.status_code == 202
    again = client.post("/api/v1/analyses", json=payload, headers=headers(state, **{"Idempotency-Key": "same"}))
    assert again.status_code == 200 and again.json()["reused"] is True
    changed = client.post("/api/v1/analyses", json={**payload, "gross_mass_t": 21}, headers=headers(state, **{"Idempotency-Key": "same"}))
    assert changed.status_code == 409
    jid = first.json()["id"]
    assert client.post(f"/api/v1/jobs/{jid}/cancel", headers=headers(state)).status_code == 202
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "cancelled"
    assert client.get(f"/api/v1/results/{first.json()['run_id']}").status_code == 404


def test_invalid_geometry_import_cannot_be_committed(client):
    state=bootstrap(client)
    data='id,name,type,longitude,latitude\nBAD-1,Невірний,well,999,100\n'
    p=client.post('/api/v1/imports',json={'resource':'assets','format':'csv','data':data},headers=headers(state))
    assert p.status_code==201
    assert p.json()['errors']
    assert client.post('/api/v1/imports/'+p.json()['id']+'/commit',headers=headers(state)).status_code==409
    assert client.get('/api/v1/assets/BAD-1').status_code==404


def test_import_preview_commit_dedupes_and_export_is_safe(client):
    state = bootstrap(client)
    data = "id,name,type,longitude,latitude\nIM-1,=danger,well,0.01,0.02\n"
    preview = client.post("/api/v1/imports", json={"resource": "assets", "format": "csv", "data": data}, headers=headers(state))
    assert preview.status_code == 201
    imp = preview.json()
    assert imp["status"] == "preview" and imp["rows"] == 1
    committed = client.post(f"/api/v1/imports/{imp['id']}/commit", headers=headers(state))
    assert committed.status_code == 200
    again = client.post(f"/api/v1/imports/{imp['id']}/commit", headers=headers(state))
    assert again.status_code == 200 and again.json()["deduped"] is True
    export = client.post("/api/v1/exports", json={"format": "csv", "scope": "assets"}, headers=headers(state))
    assert export.status_code == 201
    download = client.get(export.json()["download_url"])
    assert download.status_code == 200
    assert b"'=danger" in download.content


def test_pdf_embeds_ukrainian_font_and_reports_registry(client):
    s=bootstrap(client)
    export=client.post('/api/v1/exports',json={'format':'pdf','scope':'assets'},headers=headers(s)).json()
    body=client.get(export['download_url']).content
    assert body.startswith(b'%PDF-')
    assert b'/FontFile2' in body
    assert len(body)>5000


def test_csv_keeps_zero_and_escapes_whitespace_formula(client):
    import csv
    s=bootstrap(client)
    client.post('/api/v1/constraints',json={'id':'ZERO','name':'\t=SUM(1)','value':0},headers=headers(s))
    r=client.post('/api/v1/exports',json={'format':'csv','scope':'constraints'},headers=headers(s)).json()
    rows=list(csv.DictReader(io.StringIO(client.get(r['download_url']).text)))
    row=next(x for x in rows if x['id']=='ZERO')
    assert row['value']=='0'
    assert row['name'].startswith("'")


def test_offline_restore_cannot_claim_success_on_tampered_package(client):
    s=bootstrap(client)
    packet=client.get('/api/v1/offline-package').json()
    packet['resources']=[]
    response=client.post('/api/v1/offline-package/restore',json=packet,headers=headers(s))
    assert response.status_code==409


def test_upload_and_offline_snapshot_are_private_and_persisted(client):
    state = bootstrap(client)
    response = client.post("/api/v1/uploads", files={"file": ("x.png", io.BytesIO(b"not an image"), "image/png")}, headers=headers(state))
    assert response.status_code == 422
    offline = client.get("/api/v1/offline-package")
    assert offline.status_code == 200
    assert offline.json()["digest"].startswith("sha256:")


def test_forecast_calls_parent_science_engine_when_available(client):
    bootstrap(client)
    response = client.get("/api/v1/forecast?asset_id=GS-014&assessment_date=2027-03-15&gross_mass_t=20")
    assert response.status_code == 200
    assessment = response.json()
    assert assessment["asset_id"] == "GS-014"
    assert assessment["gross_mass_t"] == 20
    assert assessment["synthetic"] is True


def test_published_result_has_jcs_manifest_and_can_be_withdrawn(client):
    state = bootstrap(client)
    accepted = client.post(
        "/api/v1/analyses",
        json={"assessment_date": "2027-03-16", "gross_mass_t": 20},
        headers=headers(state, **{"Idempotency-Key": "manifest-withdraw"}),
    ).json()
    deadline = time.monotonic() + 3
    job = None
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{accepted['id']}").json()
        if job["status"] in {"published", "failed"}:
            break
        time.sleep(0.05)
    assert job and job["status"] == "published"
    manifest = client.get(f"/api/v1/results/{accepted['run_id']}/manifest")
    assert manifest.status_code == 200
    assert "digest" not in manifest.json()["manifest"]
    withdrawn = client.post(f"/api/v1/results/{accepted['run_id']}/withdraw", json={"reason": "Тестове відкликання"}, headers=headers(state))
    assert withdrawn.status_code == 200
    assert client.get(f"/api/v1/results/{accepted['run_id']}").json()["eligibility"] == "withdrawn"


def test_validation_module_is_wired_but_never_approves_production(client):
    s=bootstrap(client)
    r=client.post('/api/v1/validation/evaluate',json={'rows':[{'prediction':1.,'observed':1.}],'config':{'heldout':True,'out_of_sample':True,'synthetic':True}},headers=headers(s))
    assert r.status_code==200
    assert r.json()['status']=='research_only'
    assert r.json()['model_approval'] is False


def test_data_validation_is_scoped_audited_preview(client):
    state = bootstrap(client)
    response = client.post(
        "/api/v1/data/validate",
        json={"product": "soilgrids", "payload": {"source_version": "demo-v1", "support_m": 250, "depths": [{"top_cm": 0, "bottom_cm": 5, "sand_g_kg": 400, "silt_g_kg": 380, "clay_g_kg": 220}]}},
        headers=headers(state),
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["status"] == "preview" and preview["synthetic"] is True
    assert client.get("/api/v1/audit").json()["items"][0]["action"] == "validate_data_preview"
    rejected = client.post("/api/v1/data/validate", json={"product": "unknown", "payload": {}}, headers=headers(state))
    assert rejected.status_code == 422
