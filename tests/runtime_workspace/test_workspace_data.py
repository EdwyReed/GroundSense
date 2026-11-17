"""Public-data contract tests; provider doubles are test-only."""
import hashlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDSENSE_DATABASE_URL", f"sqlite:///{tmp_path}/workspace.db")
    monkeypatch.setenv("GROUNDSENSE_DATA_DIR", str(tmp_path / "data"))
    from apps.api.main import create_app
    with TestClient(create_app(), base_url="https://testserver") as value:
        value.app.state.extra_sources = {}
        yield value


def bootstrap(client):
    body = client.get("/api/v1/bootstrap").json()
    return body, {"Origin": "https://testserver", "X-CSRF-Token": body["csrf_token"]}


def asset_payload():
    return {"name": "Known point", "latitude": 59.91, "longitude": 10.75, "source_ref": "test:fixture"}


def test_default_bootstrap_is_empty_public_workspace(client):
    body, _ = bootstrap(client)
    assert body["workspace"]["mode"] == "public_data" and body["workspace"]["synthetic"] is False
    assert body["assets"] == []
    assert body["soil"] == {"composition": None, "support_m": None, "depths": []}
    assert body["map"] == {"mode": "public_data", "type": "FeatureCollection", "features": []}
    assert body["context"]["gross_mass_t"] == 20 and body["context"]["assessment_date"]


def test_public_asset_creation_is_honest_and_requires_provenance(client):
    _, headers = bootstrap(client)
    invalid = client.post("/api/v1/assets", json={"name": "Missing provenance", "geometry": {"type": "Point", "coordinates": [10.75, 59.91]}}, headers=headers)
    assert invalid.status_code == 422
    response = client.post("/api/v1/assets", json={"name": "Original registry point", "type": "well", "source_ref": "test:registry", "geometry": {"type": "Point", "coordinates": [10.75, 59.91]}}, headers=headers)
    assert response.status_code == 201
    assert response.json()["synthetic"] is False and response.json()["condition"] == "unknown"


def test_asset_context_merges_provider_results_without_network(client):
    _, headers = bootstrap(client)
    asset = client.post("/api/v1/live/assets", json=asset_payload(), headers=headers).json()
    class StaticDouble:
        def read(self, latitude, longitude):
            return {"soil": {"composition": None, "support_m": None, "depths": []}, "terrain": {"elevation_m": None}, "land_cover": {"class": None}, "sources": [{"id": "soilgrids", "status": "partial", "qc": "partial", "note": "metadata only", "retrieved_at": None, "observed_at": None, "content_sha256": None}]}
    class RemoteDouble:
        def read(self, latitude, longitude, assessment_date):
            return {"satellites": [], "history": [], "sources": [{"id": "era5-land", "status": "unavailable", "qc": "unavailable", "note": "fixture", "retrieved_at": None, "observed_at": None, "content_sha256": None}]}
    client.app.state.static_sources, client.app.state.remote_sources = StaticDouble(), RemoteDouble()
    context = client.get("/api/v1/asset-context", params={"asset_id": asset["id"], "assessment_date": "2026-10-25"})
    assert context.status_code == 200
    assert context.json()["synthetic"] is False and {x["id"] for x in context.json()["sources"]} == {"soilgrids", "era5-land"}


def test_forecast_and_job_use_live_weather_not_science_seed(client, tmp_path):
    _, headers = bootstrap(client)
    asset = client.post("/api/v1/live/assets", json=asset_payload(), headers=headers).json()
    raw = b'{"provider":"controlled"}'; digest = hashlib.sha256(raw).hexdigest(); path = tmp_path / "weather.json"; path.write_bytes(raw)
    class WeatherDouble:
        def forecast(self, latitude, longitude, assessment_date=None):
            return {"source": {"id": "controlled", "model": "controlled/v1", "content_sha256": "sha256:" + digest}, "series": [{"time": "2026-10-25T00:00:00Z", "soil_moisture_0_to_1cm": .2, "precipitation": 1., "temperature_2m": 5.}]}
        def snapshot_path(self, ident): return path
    client.app.state.live_weather = WeatherDouble()
    forecast = client.get("/api/v1/forecast", params={"asset_id": asset["id"], "assessment_date": "2026-10-25", "gross_mass_t": 20})
    assert forecast.status_code == 200 and forecast.json()["synthetic"] is False and forecast.json()["series"][0]["moisture_p10"] is None
    accepted = client.post("/api/v1/analyses", json={"asset_id": asset["id"], "assessment_date": "2026-10-25", "gross_mass_t": 20}, headers={**headers, "Idempotency-Key": "live-job"}).json()
    for _ in range(50):
        job = client.get("/api/v1/jobs/" + accepted["id"]).json()
        if job["status"] in {"published", "failed"}: break
        time.sleep(.03)
    assert job["status"] == "published"
    assert client.get("/api/v1/results/" + accepted["run_id"]).json()["assessment"]["synthetic"] is False


def test_public_bootstrap_migrates_only_legacy_live_records(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDSENSE_DATABASE_URL", f"sqlite:///{tmp_path}/migration.db")
    monkeypatch.setenv("GROUNDSENSE_DATA_DIR", str(tmp_path / "data"))
    from apps.api.main import Resource, create_app
    with TestClient(create_app(data_mode="synthetic"), base_url="https://testserver") as legacy:
        state, headers = bootstrap(legacy)
        legacy.post("/api/v1/live/assets", json=asset_payload(), headers=headers).raise_for_status()
        token, old_workspace = legacy.cookies.get("__Host-gs_session"), state["workspace"]["id"]
    public = create_app()
    with TestClient(public, base_url="https://testserver") as migrated:
        migrated.cookies.set("__Host-gs_session", token)
        body, _ = bootstrap(migrated)
        assert body["workspace"]["id"] != old_workspace
        assert [item["name"] for item in body["assets"]] == ["Known point"]
        with public.state.factory() as database:
            assert database.query(Resource).filter_by(workspace_id=old_workspace, kind="assets").count() == 12
            assert database.query(Resource).filter_by(workspace_id=body["workspace"]["id"], kind="workspace_config", logical_id="public-data-v1").count() == 1
