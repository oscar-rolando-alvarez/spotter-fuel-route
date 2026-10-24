"""Geocoding as a Chain of Responsibility (ADR-0004).

Cheapest/most specific handler first: a "lat,lng" literal, then the offline Census
gazetteer, then (optionally) Nominatim for free-form addresses. Each link returns a
Location or None ("not mine"); the chain raises if nobody resolves the query.
"""

import re
from collections.abc import Sequence

from fuel_route.domain.errors import LocationNotFoundError
from fuel_route.domain.model import Location
from fuel_route.domain.ports import Boundary, Geocoder
from fuel_route.models import Place

from .http import JsonHttpClient
from .names import normalize_state, place_key

_COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_COUNTRY = {"usa", "us", "united states"}


class CoordinateGeocoder:
    name = "coordinates"

    def __init__(self, boundary: Boundary):
        self._boundary = boundary

    def geocode(self, query: str) -> Location | None:
        if not (m := _COORDS.match(query)):
            return None
        lat, lng = float(m[1]), float(m[2])
        if not self._boundary.contains((lat, lng)):
            # Definitive answer: it *is* coordinates, just not in scope. Stop the chain.
            raise LocationNotFoundError(f"{query!r} is not inside the USA (expected 'lat,lng').")
        return Location(query, f"{lat:.5f}, {lng:.5f}", lat, lng, self.name)


class GazetteerGeocoder:
    """'City, ST' / 'City, State' / 'City, ST, USA' via the indexed Place table."""

    name = "gazetteer"

    def geocode(self, query: str) -> Location | None:
        parts = [p.strip() for p in query.split(",")]
        if len(parts) >= 3 and parts[-1].lower() in _COUNTRY:
            parts = parts[:-1]
        if len(parts) < 2 or not (state := normalize_state(parts[-1])):
            return None
        place = Place.objects.filter(state=state, key=place_key(parts[-2])).first()
        if place is None:
            return None
        return Location(query, f"{place.name}, {state}", place.lat, place.lng, self.name)


class NominatimGeocoder:
    """Free-form addresses. Network-bound: wrap it in CachedGeocoder."""

    name = "nominatim"

    def __init__(self, base_url: str, http: JsonHttpClient, boundary: Boundary):
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._boundary = boundary

    def geocode(self, query: str) -> Location | None:
        hits = self._http.get_json(
            f"{self._base_url}/search",
            params={"q": query, "countrycodes": "us", "format": "jsonv2", "limit": 1},
        )
        if not hits:
            return None
        lat, lng = float(hits[0]["lat"]), float(hits[0]["lon"])
        if not self._boundary.contains((lat, lng)):
            return None
        return Location(query, hits[0].get("display_name", query), lat, lng, self.name)


class GeocoderChain:
    """LocationResolver port: runs the handlers in order until one resolves the query."""

    def __init__(self, handlers: Sequence[Geocoder]):
        self._handlers = tuple(handlers)

    def resolve(self, query: str) -> Location:
        query = query.strip()
        if not query:
            raise LocationNotFoundError("Location is empty.")
        for handler in self._handlers:
            if (loc := handler.geocode(query)) is not None:
                return loc
        raise LocationNotFoundError(f"Could not find {query!r} in the USA. Try 'City, ST' or 'lat,lng'.")
