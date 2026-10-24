"""Driving route from the public OSRM server: the single external call per plan."""

from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from .geo import LatLng
from .http import UpstreamError, get_json

METERS_PER_MILE = 1609.344


@dataclass(frozen=True)
class Route:
    distance_miles: float
    duration_hours: float
    coordinates: list[LatLng]  # (lat, lng), full resolution


def fetch_route(start: LatLng, finish: LatLng) -> Route:
    cache_key = f"osrm:{start[0]:.5f},{start[1]:.5f}:{finish[0]:.5f},{finish[1]:.5f}"
    if (cached := cache.get(cache_key)) is not None:
        return cached

    coords = f"{start[1]},{start[0]};{finish[1]},{finish[0]}"  # OSRM wants lng,lat
    data = get_json(
        f"{settings.FUEL_ROUTE['OSRM_URL']}/route/v1/driving/{coords}",
        params={"overview": "full", "geometries": "geojson", "steps": "false", "alternatives": "false"},
    )
    if data.get("code") != "Ok" or not data.get("routes"):
        raise UpstreamError(f"OSRM: {data.get('code')} {data.get('message', '')}".strip())

    best = data["routes"][0]
    route = Route(
        distance_miles=best["distance"] / METERS_PER_MILE,
        duration_hours=best["duration"] / 3600,
        coordinates=[(lat, lng) for lng, lat in best["geometry"]["coordinates"]],
    )
    cache.set(cache_key, route)
    return route
