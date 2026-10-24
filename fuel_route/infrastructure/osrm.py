"""OSRM adapter for the RoutingProvider port: the single external call per trip (ADR-0003)."""

from fuel_route.domain.errors import ProviderUnavailableError
from fuel_route.domain.model import LatLng, Route

from .http import JsonHttpClient

METERS_PER_MILE = 1609.344


class OsrmRoutingProvider:
    def __init__(self, base_url: str, http: JsonHttpClient):
        self._base_url = base_url.rstrip("/")
        self._http = http

    def route(self, start: LatLng, finish: LatLng) -> Route:
        coords = f"{start[1]},{start[0]};{finish[1]},{finish[0]}"  # OSRM wants lng,lat
        data = self._http.get_json(
            f"{self._base_url}/route/v1/driving/{coords}",
            params={"overview": "full", "geometries": "geojson", "steps": "false", "alternatives": "false"},
        )
        if data.get("code") != "Ok" or not data.get("routes"):
            raise ProviderUnavailableError(f"OSRM: {data.get('code')} {data.get('message', '')}".strip())

        best = data["routes"][0]
        return Route(
            distance_miles=best["distance"] / METERS_PER_MILE,
            duration_hours=best["duration"] / 3600,
            coordinates=tuple((lat, lng) for lng, lat in best["geometry"]["coordinates"]),
        )
