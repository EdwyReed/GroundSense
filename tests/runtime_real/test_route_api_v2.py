"""Entry-point integration gates for the new route-first product.

No live providers are queried by these tests: requests stop at session, CSRF or
input validation. Provider behavior lives in the isolated route adapter tests.
"""
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDSENSE_DATABASE_URL", f"sqlite:///{tmp_path}/route-api.db")
    monkeypatch.setenv("GROUNDSENSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GROUNDSENSE_PUBLIC_ORIGIN", "https://testserver")
    from apps.api.main import create_app
    with TestClient(create_app(), base_url="https://testserver") as value:
        yield value


def trip():
    return {
        "origin": {"longitude": 10.7387, "latitude": 59.9139, "label": "Reference A"},
        "destination": {"longitude": 10.7849, "latitude": 59.9399, "label": "Reference B"},
        "trip_date": "2026-10-26",
        "vehicle": {"kind": "truck_6x6", "gross_mass_t": 20},
    }


def test_place_search_requires_existing_browser_session(client):
    assert client.get("/api/v1/places", params={"q": "Oslo"}).status_code == 401


def test_route_search_requires_csrf_and_same_origin(client):
    bootstrap = client.get("/api/v1/bootstrap").json()
    assert client.post("/api/v1/route-plans", json=trip()).status_code == 403
    headers = {"X-CSRF-Token": bootstrap["csrf_token"], "Origin": "https://wrong.example"}
    assert client.post("/api/v1/route-plans", headers=headers, json=trip()).status_code == 403


def test_route_search_validates_input_before_any_provider_call(client):
    bootstrap = client.get("/api/v1/bootstrap").json()
    headers = {"X-CSRF-Token": bootstrap["csrf_token"], "Origin": "https://testserver"}
    request = trip()
    request["vehicle"]["gross_mass_t"] = True
    response = client.post("/api/v1/route-plans", headers=headers, json=request)
    assert response.status_code == 422, response.text
