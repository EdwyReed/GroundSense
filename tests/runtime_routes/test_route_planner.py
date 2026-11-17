from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from apps.api.route_planner import RoutePlanner, _payload, register_route_endpoints


NOW = datetime(2026, 10, 26, tzinfo=UTC)
VALID = {
    "origin": {"longitude": 10.7387, "latitude": 59.9139, "label": "Oslo A"},
    "destination": {"longitude": 10.7849, "latitude": 59.9399, "label": "Oslo B"},
    "trip_date": "2026-10-26",
    "vehicle": {"kind": "truck_6x6", "gross_mass_t": 20},
}
ROUTE = {
    "code": "Ok",
    "routes": [
        {"distance": 5931.5, "geometry": {"type": "LineString", "coordinates": [[10.7387, 59.9139], [10.7849, 59.9399]]}},
        {"distance": 6499.9, "geometry": {"type": "LineString", "coordinates": [[10.7387, 59.9139], [10.75, 59.92], [10.7849, 59.9399]]}},
    ],
}


def transport(route=ROUTE, places=None, status_code=200, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        payload = places if "photon" in str(request.url) else route
        return httpx.Response(status_code, json=payload, request=request)
    return httpx.MockTransport(handler)


def planner(**kwargs):
    return RoutePlanner(transport=transport(**kwargs), clock=lambda: NOW)


def test_plan_returns_actual_osrm_geometry_and_honest_unassessed_fields():
    result = planner().plan(VALID)

    assert result["status"] == "ready"
    assert [route["distance_m"] for route in result["routes"]] == [5931.5, 6499.9]
    assert result["routes"][0]["geometry"] == ROUTE["routes"][0]["geometry"]
    assert result["routes"][0]["surface"] == {"paved_m": None, "unpaved_m": None}
    assert result["vehicle_assessment"] == result["date_assessment"] == "not_assessed"
    assert result["synthetic"] is False
    assert "вантажівки" in result["warnings_uk"][0]


def test_plan_limits_alternatives_and_uses_fixed_osrm_profile():
    calls = []
    result = planner(route={"code": "Ok", "routes": ROUTE["routes"] * 2}, calls=calls).plan(VALID)

    assert len(result["routes"]) == 3
    assert calls[0].url.host == "router.project-osrm.org"
    assert calls[0].url.path.startswith("/route/v1/driving/")
    assert calls[0].url.params["alternatives"] == "true"


@pytest.mark.parametrize("change", [
    {"origin": {"longitude": "10.7", "latitude": 59.9}},
    {"origin": {"longitude": float("nan"), "latitude": 59.9}},
    {"destination": {"longitude": 181, "latitude": 59.9}},
    {"trip_date": "2026-02-30"},
    {"vehicle": {"kind": "truck_6x6", "gross_mass_t": True}},
    {"vehicle": {"kind": "tank", "gross_mass_t": 20}},
    {"vehicle": {"kind": [], "gross_mass_t": 20}},
    {"vehicle": {"kind": "truck_6x6", "gross_mass_t": 10 ** 1000}},
])
def test_plan_rejects_invalid_coordinate_date_and_vehicle(change):
    payload = {**VALID, **change}
    with pytest.raises(ValueError, match="[Нн]екорект"):
        planner().plan(payload)


def test_plan_rejects_oversized_or_far_apart_trip_before_network():
    calls = []
    oversized = {**VALID, "origin": {"longitude": 10.7, "latitude": 59.9, "label": "x" * 121}}
    with pytest.raises(ValueError):
        planner(calls=calls).plan(oversized)

    remote = {**VALID, "destination": {"longitude": 30.5, "latitude": 50.4}}
    with pytest.raises(ValueError, match="далек"):
        planner(calls=calls).plan(remote)
    assert calls == []


def test_plan_distinguishes_no_route_from_provider_error():
    no_route = planner(route={"code": "NoRoute", "message": "Impossible route"}).plan(VALID)
    unavailable = planner(route={"code": "Ok"}, status_code=503).plan(VALID)

    assert no_route["status"] == "no_route"
    assert no_route["routes"] == []
    assert unavailable["status"] == "unavailable"
    assert unavailable["routes"] == []


def test_plan_rejects_invalid_geometry_and_excessive_provider_snap():
    bad_geometry = {"code": "Ok", "routes": [{"distance": 3, "geometry": {"type": "LineString", "coordinates": [[999, 0], [0, 0]]}}]}
    invalid = planner(route=bad_geometry).plan(VALID)
    far = {"code": "Ok", "routes": [{"distance": 3, "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.1, 0.1]]}}]}
    snapped = planner(route=far).plan(VALID)

    assert invalid["status"] == "unavailable"
    assert snapped["status"] == "unavailable"


def test_places_validates_query_and_returns_bounded_photon_points():
    places = {"features": [
        {"geometry": {"type": "Point", "coordinates": [10.75, 59.91]}, "properties": {"name": "Oslo", "country": "Norway"}},
        {"geometry": {"type": "Point", "coordinates": [10.75, 59.91]}, "properties": {"name": "Oslo", "country": "Norway"}},
        {"geometry": {"type": "Point", "coordinates": [200, 59.91]}, "properties": {"name": "bad"}},
    ]}
    result = planner(places=places).places(" Oslo ")

    assert result == {"places": [{"longitude": 10.75, "latitude": 59.91, "label": "Oslo, Norway"}], "source": {"id": "photon"}, "status": "ready"}
    with pytest.raises(ValueError, match="Пошуков"):
        planner().places(" ")


def test_photon_does_not_force_an_unsupported_language():
    calls = []
    planner(places={"features": []}, calls=calls).places("Oslo")
    assert "lang" not in calls[0].url.params


def test_endpoint_uses_session_mutation_and_source_budget():
    app = FastAPI()
    budgets = []
    class Session:
        workspace_id = "w-1"

    register_route_endpoints(app, lambda: Session(), lambda: Session(), lambda workspace: budgets.append(workspace), planner=planner())
    client = TestClient(app)

    response = client.post("/api/v1/route-plans", json=VALID)
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    places = client.get("/api/v1/places", params={"q": "Oslo"})
    assert places.status_code == 200
    assert budgets == ["w-1", "w-1"]


def test_endpoint_returns_ukrainian_422_for_malformed_payload():
    app = FastAPI()
    class Session:
        workspace_id = "w-1"
    register_route_endpoints(app, lambda: Session(), lambda: Session(), lambda _: None, planner=planner())

    response = TestClient(app).post("/api/v1/route-plans", json={})
    assert response.status_code == 422
    assert "detail" in response.json()


def test_budget_rejection_prevents_provider_request():
    app = FastAPI()
    calls = []
    class Session:
        workspace_id = "quota-test"
    def reject(_):
        raise HTTPException(429, "quota")
    register_route_endpoints(app, lambda: Session(), lambda: Session(), reject, planner=planner(calls=calls))
    assert TestClient(app).post("/api/v1/route-plans", json=VALID).status_code == 429
    assert calls == []


def test_unsnappable_point_is_not_reported_as_provider_outage():
    result = planner(route={"code": "NoSegment"}, status_code=400).plan(VALID)
    assert result["status"] == "no_route"
    assert result["routes"] == []


def test_chunked_non_json_request_stops_reading_at_the_route_limit():
    consumed = []
    chunks = [b"x" * 4096, b"x" * 4096, b"x", b"must-not-be-read"]
    async def receive():
        index = len(consumed)
        consumed.append(index)
        return {"type": "http.request", "body": chunks[index], "more_body": index < len(chunks) - 1}
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/route-plans", "headers": [(b"content-type", b"text/plain"), (b"transfer-encoding", b"chunked")]}, receive)

    with pytest.raises(HTTPException) as error:
        asyncio.run(_payload(request, RoutePlanner.MAX_REQUEST_BYTES))
    assert error.value.status_code == 413
    assert consumed == [0, 1, 2], "oversized body was fully buffered before rejection"


@pytest.mark.parametrize("distance,midpoint", [
    (9_999_999, None),
    (5931.5, [-170, 0]),
    (100_000, None),
])
def test_provider_route_extent_and_distance_are_bounded(distance, midpoint):
    coordinates = [[10.7387, 59.9139], [10.7849, 59.9399]]
    if midpoint is not None:
        coordinates.insert(1, midpoint)
    result = planner(route={"code": "Ok", "routes": [{"distance": distance, "geometry": {"type": "LineString", "coordinates": coordinates}}]}).plan(VALID)
    assert result["status"] == "unavailable"
    assert result["routes"] == []


@pytest.mark.parametrize("code", [{}, []])
def test_malformed_provider_code_is_unavailable_not_a_crash(code):
    result = planner(route={"code": code}).plan(VALID)
    assert result["status"] == "unavailable"
