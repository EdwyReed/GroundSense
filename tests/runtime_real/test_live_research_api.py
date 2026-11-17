"""Live-input research API seam. Weather below is a labelled test double, not live proof."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import time

import pytest
import rfc8785
from fastapi.testclient import TestClient


def weather_fixture(rain=0.0):
    start = datetime(2026, 10, 25, tzinfo=UTC)
    rows = [{"time": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
             "temperature_2m": 10.0, "soil_temperature_0cm": 10.0,
             "soil_moisture_0_to_1cm": .30, "soil_moisture_1_to_3cm": .30,
             "soil_moisture_3_to_9cm": .30, "precipitation": rain if i else 999.0,
             "et0_fao_evapotranspiration": .1, "snow_depth": 0.0, "snowfall": 0.0}
            for i in range(73)]
    return {"assessment_date": "2026-10-25", "series": rows[:24], "research_series": rows,
            "source": {"id": "test-only", "model": "test-weather/1", "issue_time": None,
                       "retrieved_at": "2026-10-25T12:00:00Z", "content_sha256": "sha256:" + "a" * 64},
            "grid_point": {"latitude": 59.66, "longitude": 10.78},
            "units": {"precipitation": "mm", "et0_fao_evapotranspiration": "mm"}}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDSENSE_DATABASE_URL", f"sqlite:///{tmp_path}/research.db")
    monkeypatch.setenv("GROUNDSENSE_DATA_DIR", str(tmp_path / "data"))
    from apps.api.main import create_app
    with TestClient(create_app(), base_url="https://testserver") as client:
        bootstrap = client.get("/api/v1/bootstrap").json()
        headers = {"Origin": "https://testserver", "X-CSRF-Token": bootstrap["csrf_token"]}
        point = client.post("/api/v1/assets", headers=headers, json={
            "name": "Research integration test point", "type": "other", "source_ref": "test-only",
            "geometry": {"type": "Point", "coordinates": [10.78, 59.66]}}).json()
        class Weather:
            value = weather_fixture()
            def forecast(self, lat, lon, day):
                assert (lat, lon, day) == (59.66, 10.78, "2026-10-25")
                return deepcopy(self.value)
        provider = Weather()
        client.app.state.live_weather = provider
        yield client, headers, point, provider


def query(point, mass=20):
    return {"asset_id": point["id"], "assessment_date": "2026-10-25", "gross_mass_t": mass}


def test_real_forecast_executes_water_balance_and_keeps_vehicle_gate_separate(setup):
    client, _, point, _ = setup
    response = client.get("/api/v1/forecast", params=query(point))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["mode"] == "research_water_balance"
    assert value["synthetic"] is False
    assert value["model_version"] == "live-warm-water/1"
    assert value["research"]["status"] == "research_only"
    assert len(value["research"]["scenarios"]) == 3
    assert value["research"]["metrics"]["max_mass_residual_mm"] < 1e-8
    assert value["research"]["metrics"]["precipitation_mm"] == 0
    assert value["condition"] == value["research"]["condition"]
    assert value["mobility"]["kind"] == "unavailable"
    assert "VEHICLE_ENVELOPE_UNSUPPORTED" in value["mobility"]["reason_codes"]
    assert value["series"][0]["moisture_p50"] == .30
    assert all(row["time"].startswith("2026-10-25") for row in value["series"])
    assert value["forecast_issue_time"] is None
    assert value["input_snapshot"]["asset"]["geometry"] == point["geometry"]
    assert value["input_snapshot"]["weather"]["research_series"]


def test_real_calculation_changes_with_rain_but_not_gross_mass(setup):
    client, _, point, provider = setup
    dry = client.get("/api/v1/forecast", params=query(point)).json()
    heavy = client.get("/api/v1/forecast", params=query(point, 40)).json()
    assert dry["research"] == heavy["research"]
    provider.value = weather_fixture(rain=1.0)
    wet = client.get("/api/v1/forecast", params=query(point)).json()
    assert wet["research"]["metrics"]["precipitation_mm"] == 72.0
    assert wet["research"]["scenarios"][1]["steps"] != dry["research"]["scenarios"][1]["steps"]
    # A computed environmental signal never overwrites the registry as field truth.
    assert client.get("/api/v1/assets/" + point["id"]).json()["condition"] == "unknown"


def test_missing_research_inputs_preserve_provider_values_and_explain_abstention(setup):
    client, _, point, provider = setup
    provider.value.pop("research_series")
    value = client.get("/api/v1/forecast", params=query(point)).json()
    assert value["series"] and value["synthetic"] is False
    assert value["research"]["status"] == "abstained"
    assert value["condition"] == "unknown"
    assert value["research"]["reason_codes"]
    assert value["mobility"]["kind"] == "unavailable"


def test_published_job_contains_exact_replay_snapshot_and_research_result(setup):
    client, headers, point, _ = setup
    response = client.post("/api/v1/analyses", headers={**headers, "Idempotency-Key": "research-job"}, json=query(point))
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["mode"] == "research_water_balance"
    for _ in range(100):
        state = client.get("/api/v1/jobs/" + job["id"]).json()
        if state["status"] in {"published", "failed"}:
            break
        time.sleep(.03)
    assert state["status"] == "published", state
    result = client.get("/api/v1/results/" + job["run_id"]).json()
    manifest = client.get("/api/v1/results/" + job["run_id"] + "/manifest").json()["manifest"]
    assessment = result["assessment"]
    assert assessment["research"]["status"] == "research_only"
    assert manifest["input_snapshot_digest"] == "sha256:" + hashlib.sha256(rfc8785.dumps(assessment["input_snapshot"])).hexdigest()
    assert manifest["assessment_digest"] == "sha256:" + hashlib.sha256(rfc8785.dumps(assessment)).hexdigest()
    # Independent anonymous browser cannot retrieve another workspace's calculation.
    with TestClient(client.app, base_url="https://testserver") as other:
        other.get("/api/v1/bootstrap")
        assert other.get("/api/v1/results/" + job["run_id"]).status_code == 404
