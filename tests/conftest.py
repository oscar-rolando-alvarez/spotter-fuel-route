import pytest
from django.core.cache import cache

from fuel_route import container
from fuel_route.models import FuelStation, Place


@pytest.fixture(autouse=True)
def _isolate_caches():
    cache.clear()
    container.reset()
    yield
    cache.clear()
    container.reset()


def osrm_payload(coords_latlng, miles):
    """A minimal OSRM /route response for the given (lat, lng) polyline."""
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": miles * 1609.344,
                "duration": miles / 60 * 3600,
                "geometry": {"type": "LineString", "coordinates": [[lng, lat] for lat, lng in coords_latlng]},
            }
        ],
    }


# A straight east-west road along 40°N from 100°W to 88°W (~635 mi).
LINE = [(40.0, -100.0 + i * 0.1) for i in range(121)]


@pytest.fixture
def corridor_data(db):
    Place.objects.bulk_create(
        [
            Place(state="NE", key="westtown", name="Westtown", lat=40.0, lng=-100.0),
            Place(state="IL", key="easttown", name="Easttown", lat=40.0, lng=-88.0),
        ]
    )
    # (opis_id, lng, price): cheap station mid-way, pricey ones elsewhere, one far off-route.
    rows = [(1, -99.0, 3.50), (2, -95.0, 2.90), (3, -92.0, 3.60), (4, -89.0, 3.40)]
    FuelStation.objects.bulk_create(
        [
            FuelStation(
                opis_id=i, name=f"Stop {i}", address="I-80", city="Somewhere", state="NE", price=p, lat=40.0, lng=lng
            )
            for i, lng, p in rows
        ]
        + [
            FuelStation(
                opis_id=99, name="Far away", address="", city="Nowhere", state="KS", price=1.00, lat=38.0, lng=-95.0
            )
        ]
    )
