from unittest import mock

import pytest

from fuel_route.models import Place
from fuel_route.services import geocoding


@pytest.fixture
def places(db):
    Place.objects.create(state="IL", key="chicago", name="Chicago", lat=41.84, lng=-87.68)
    Place.objects.create(state="TX", key="ftworth", name="Fort Worth", lat=32.78, lng=-97.35)


def test_coordinates_need_no_lookup(places):
    loc = geocoding.resolve("39.74, -104.99")
    assert (loc.lat, loc.lng, loc.source) == (39.74, -104.99, "coordinates")


def test_coordinates_outside_usa_rejected(places):
    with pytest.raises(geocoding.GeocodingError):
        geocoding.resolve("48.85,2.35")


@pytest.mark.parametrize("q", ["Chicago, IL", "chicago, illinois", "Chicago, IL, USA"])
def test_city_state_from_gazetteer(places, q):
    loc = geocoding.resolve(q)
    assert loc.source == "gazetteer" and loc.label == "Chicago, IL"


def test_abbreviation_variants(places):
    assert geocoding.resolve("Ft. Worth, TX").label == "Fort Worth, TX"


@mock.patch("fuel_route.services.geocoding.get_json")
def test_falls_back_to_nominatim_and_caches(get_json, places):
    get_json.return_value = [{"lat": "36.17", "lon": "-115.14", "display_name": "Las Vegas, NV"}]
    first = geocoding.resolve("3570 Las Vegas Blvd S")
    second = geocoding.resolve("3570 Las Vegas Blvd S")
    assert first == second and first.source == "nominatim"
    assert get_json.call_count == 1


@mock.patch("fuel_route.services.geocoding.get_json")
def test_fallback_can_be_disabled(get_json, places, settings):
    settings.FUEL_ROUTE = {**settings.FUEL_ROUTE, "GEOCODER_FALLBACK": False}
    with pytest.raises(geocoding.GeocodingError):
        geocoding.resolve("somewhere unknown")
    get_json.assert_not_called()
