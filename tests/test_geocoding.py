from unittest import mock

import pytest

from fuel_route.domain.errors import LocationNotFoundError
from fuel_route.infrastructure.caching import CachedGeocoder
from fuel_route.infrastructure.geocoding import (
    CoordinateGeocoder,
    GazetteerGeocoder,
    GeocoderChain,
    NominatimGeocoder,
)
from fuel_route.models import Place


@pytest.fixture
def places(db):
    Place.objects.create(state="IL", key="chicago", name="Chicago", lat=41.84, lng=-87.68)
    Place.objects.create(state="TX", key="ftworth", name="Fort Worth", lat=32.78, lng=-97.35)


@pytest.fixture
def nominatim_http():
    http = mock.Mock()
    http.get_json.return_value = [{"lat": "36.17", "lon": "-115.14", "display_name": "Las Vegas, NV"}]
    return http


def chain(*extra):
    return GeocoderChain([CoordinateGeocoder(), GazetteerGeocoder(), *extra])


def test_coordinates_need_no_lookup(places):
    loc = chain().resolve("39.74, -104.99")
    assert (loc.lat, loc.lng, loc.source) == (39.74, -104.99, "coordinates")


def test_coordinates_outside_usa_stop_the_chain(places, nominatim_http):
    with pytest.raises(LocationNotFoundError, match="not inside the USA"):
        chain(NominatimGeocoder("https://n", nominatim_http)).resolve("48.85,2.35")
    nominatim_http.get_json.assert_not_called()


@pytest.mark.parametrize("q", ["Chicago, IL", "chicago, illinois", "Chicago, IL, USA"])
def test_city_state_from_gazetteer(places, q):
    loc = chain().resolve(q)
    assert loc.source == "gazetteer" and loc.label == "Chicago, IL"


def test_abbreviation_variants(places):
    assert chain().resolve("Ft. Worth, TX").label == "Fort Worth, TX"


def test_gazetteer_hit_never_reaches_network(places, nominatim_http):
    chain(NominatimGeocoder("https://n", nominatim_http)).resolve("Chicago, IL")
    nominatim_http.get_json.assert_not_called()


def test_falls_back_to_cached_nominatim(places, nominatim_http):
    from django.core.cache import cache

    resolver = chain(CachedGeocoder(NominatimGeocoder("https://n", nominatim_http), cache, 60))
    first = resolver.resolve("3570 Las Vegas Blvd S")
    second = resolver.resolve("3570 las vegas blvd s ")
    assert first.source == "nominatim" and (first.lat, first.lng) == (second.lat, second.lng)
    assert nominatim_http.get_json.call_count == 1


def test_unresolvable_query_raises(places):
    with pytest.raises(LocationNotFoundError, match="Could not find"):
        chain().resolve("somewhere unknown")
    with pytest.raises(LocationNotFoundError, match="empty"):
        chain().resolve("   ")
