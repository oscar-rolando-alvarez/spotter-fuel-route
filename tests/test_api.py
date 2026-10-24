from unittest import mock

import pytest
import requests

from tests.conftest import LINE, osrm_payload

URL = "/api/v1/route-plan/"


@pytest.fixture
def fake_osrm():
    """Patch the shared HTTP session so tests also exercise call counting."""
    resp = mock.Mock(status_code=200)
    resp.json.return_value = osrm_payload(LINE, 636)
    resp.raise_for_status.return_value = None
    with mock.patch("fuel_route.services.http.session") as session:
        session.return_value.get.return_value = resp
        yield session.return_value.get


def test_plan_returns_route_stops_and_cost(client, corridor_data, fake_osrm):
    r = client.get(URL, {"start": "Westtown, NE", "finish": "Easttown, IL"})
    assert r.status_code == 200, r.json()
    body = r.json()

    assert body["summary"]["distance_miles"] == 636
    assert body["summary"]["stations_in_corridor"] == 4  # the off-route station is excluded
    [stop] = body["fuel_stops"]
    assert stop["station"]["opis_id"] == 2  # the $2.90 station, skipping pricier ones
    assert stop["price_per_gallon"] == 2.9
    assert stop["gallons"] == pytest.approx(13.6, abs=0.3)
    assert body["summary"]["total_fuel_cost"] == pytest.approx(stop["cost"])
    assert body["route"]["geometry"]["type"] == "LineString"
    assert body["route"]["geometry"]["coordinates"][0] == [-100.0, 40.0]
    assert body["meta"]["external_api_calls"] == 1
    assert body["map_url"].startswith("http://testserver/api/v1/route-plan/map/?")
    fake_osrm.assert_called_once()


def test_post_json_and_cache(client, corridor_data, fake_osrm):
    payload = {"start": "Westtown, NE", "finish": "Easttown, IL"}
    first = client.post(URL, payload, content_type="application/json").json()
    second = client.post(URL, payload, content_type="application/json").json()
    assert first["meta"]["cache_hit"] is False
    assert second["meta"]["cache_hit"] is True
    assert second["meta"]["external_api_calls"] == 0
    assert first["fuel_stops"] == second["fuel_stops"]
    fake_osrm.assert_called_once()


def test_coordinates_input(client, corridor_data, fake_osrm):
    r = client.get(URL, {"start": "40.0,-100.0", "finish": "40.0,-88.0"})
    assert r.status_code == 200
    assert r.json()["start"]["source"] == "coordinates"


def test_validation_errors(client, db):
    r = client.get(URL, {"start": "Westtown, NE"})
    assert r.status_code == 400
    assert "finish" in r.json()["detail"]
    r = client.get(URL, {"start": "a", "finish": "b", "start_fuel_gallons": 80})
    assert r.status_code == 400


def test_unknown_location(client, corridor_data, settings):
    settings.FUEL_ROUTE = {**settings.FUEL_ROUTE, "GEOCODER_FALLBACK": False}
    r = client.get(URL, {"start": "Atlantis, ZZ", "finish": "Easttown, IL"})
    assert r.status_code == 400
    assert r.json()["error"] == "location_not_found"


def test_empty_tank_without_station_at_origin_is_422(client, corridor_data, fake_osrm):
    r = client.get(URL, {"start": "Westtown, NE", "finish": "Easttown, IL", "start_fuel_gallons": 0})
    assert r.status_code == 422
    assert r.json()["error"] == "no_feasible_fuel_plan"


def test_upstream_failure_is_502(client, corridor_data):
    with mock.patch("fuel_route.services.http.session") as session:
        session.return_value.get.side_effect = requests.ConnectionError("down")
        r = client.get(URL, {"start": "Westtown, NE", "finish": "Easttown, IL"})
    assert r.status_code == 502
    assert r.json()["error"] == "routing_unavailable"


def test_map_view_renders(client, corridor_data, fake_osrm):
    r = client.get("/api/v1/route-plan/map/", {"start": "Westtown, NE", "finish": "Easttown, IL"})
    assert r.status_code == 200
    html = r.content.decode()
    assert "leaflet" in html and "Stop 2" in html


def test_health(client, corridor_data):
    assert client.get("/api/v1/health/").json() == {"status": "ok", "stations": 5, "indexed": 5}
