"""Off-road analysis must never depend on or masquerade as road routing."""
import pytest
from fastapi.testclient import TestClient

TRIP = {"origin": {"longitude": 10.73, "latitude": 59.982},
        "destination": {"longitude": 10.75, "latitude": 60.0},
        "trip_date": "2026-10-26", "vehicle": {"kind": "truck_6x6", "gross_mass_t": 20}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDSENSE_DATABASE_URL", f"sqlite:///{tmp_path}/terrain.db")
    monkeypatch.setenv("GROUNDSENSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GROUNDSENSE_PUBLIC_ORIGIN", "https://testserver")
    from apps.api.main import create_app
    from apps.api.route_planner import RoutePlanner
    def forbidden(*args, **kwargs):
        raise AssertionError("Off-road analysis called a road routing provider")
    monkeypatch.setattr(RoutePlanner, "_get_json", forbidden)
    with TestClient(create_app(), base_url="https://testserver") as value:
        yield value


def test_terrain_plan_is_server_bound_unsnapped_analysis_not_a_route(client):
    boot = client.get("/api/v1/bootstrap").json()
    headers = {"Origin": "https://testserver", "X-CSRF-Token": boot["csrf_token"]}
    response = client.post("/api/v1/terrain-plans", json=TRIP, headers=headers)
    assert response.status_code == 200
    plan = response.json()
    assert plan["analysis_kind"] == "terrain_transect"
    assert plan["source"]["id"] == "user-transect" and plan["source"]["profile"] == "not_routed"
    assert len(plan["routes"]) == 1 and len(plan["plan_id"]) == 32
    line = plan["routes"][0]
    assert line["geometry_kind"] == "analysis_transect"
    assert line["conditions"]["status"] == "not_assessed"
    assert line["geometry"]["coordinates"][0] == [10.73, 59.982]
    assert line["geometry"]["coordinates"][-1] == [10.75, 60.0]
    assert len(line["geometry"]["coordinates"]) == 25
    assert "не маршрут" in " ".join(plan["warnings_uk"]).lower()
    saved = client.app.state.route_plan_store.get(boot["workspace"]["id"], plan["plan_id"])
    assert saved["analysis_kind"] == "terrain_transect"


@pytest.mark.parametrize("change", [
    {"destination": TRIP["origin"]},
    {"destination": {"longitude": 11.75, "latitude": 60.0}},
    {"origin": {"longitude": 179.99, "latitude": 60}, "destination": {"longitude": -179.99, "latitude": 60}},
    {"origin": {"longitude": True, "latitude": 60}},
    {"trip_date": "bad"},
])
def test_terrain_plan_rejects_invalid_extent_or_trip(client, change):
    boot = client.get("/api/v1/bootstrap").json()
    response = client.post("/api/v1/terrain-plans", json={**TRIP, **change}, headers={"Origin": "https://testserver", "X-CSRF-Token": boot["csrf_token"]})
    assert response.status_code == 422


def test_terrain_plans_require_mutation_guards_and_bound_streamed_body(client):
    assert client.post("/api/v1/terrain-plans", json=TRIP).status_code == 401
    boot = client.get("/api/v1/bootstrap").json()
    assert client.post("/api/v1/terrain-plans", json=TRIP).status_code == 403
    headers = {"Origin": "https://testserver", "X-CSRF-Token": boot["csrf_token"], "Content-Type": "text/plain"}
    response = client.post("/api/v1/terrain-plans", headers=headers, content=iter([b"x" * 8192, b"x"]))
    assert response.status_code == 413
