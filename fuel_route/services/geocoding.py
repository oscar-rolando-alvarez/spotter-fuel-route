"""Resolve user input to coordinates, offline whenever possible.

Order: "lat,lng" literal -> "City, ST" via the local Census gazetteer -> Nominatim
(only for free-form addresses, cached, can be disabled with GEOCODER_FALLBACK=0).
"""

import hashlib
import re
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from fuel_route.models import Place

from .geo import in_usa
from .http import get_json
from .names import normalize_state, place_key

_COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class GeocodingError(Exception):
    pass


@dataclass(frozen=True)
class Location:
    query: str
    label: str
    lat: float
    lng: float
    source: str  # "coordinates" | "gazetteer" | "nominatim"

    @property
    def point(self) -> tuple[float, float]:
        return self.lat, self.lng


def resolve(query: str) -> Location:
    query = query.strip()
    if not query:
        raise GeocodingError("Location is empty.")

    if m := _COORDS.match(query):
        lat, lng = float(m[1]), float(m[2])
        if not in_usa((lat, lng)):
            raise GeocodingError(f"{query!r} is not inside the USA (expected 'lat,lng').")
        return Location(query, f"{lat:.5f}, {lng:.5f}", lat, lng, "coordinates")

    if loc := _from_gazetteer(query):
        return loc

    if settings.FUEL_ROUTE["GEOCODER_FALLBACK"] and (loc := _from_nominatim(query)):
        return loc

    raise GeocodingError(f"Could not find {query!r} in the USA. Try 'City, ST' or 'lat,lng'.")


def _from_gazetteer(query: str) -> Location | None:
    parts = [p.strip() for p in query.split(",")]
    if len(parts) < 2:
        return None
    # Accept "City, ST", "City, State" and "City, ST, USA".
    if parts[-1].lower() in {"usa", "us", "united states"} and len(parts) >= 3:
        parts = parts[:-1]
    state = normalize_state(parts[-1])
    city = parts[-2]
    if not state:
        return None
    place = Place.objects.filter(state=state, key=place_key(city)).first()
    if place is None:
        return None
    return Location(query, f"{place.name}, {state}", place.lat, place.lng, "gazetteer")


def _from_nominatim(query: str) -> Location | None:
    cache_key = "nominatim:" + hashlib.sha1(query.lower().encode()).hexdigest()
    if (cached := cache.get(cache_key)) is not None:
        return cached or None

    hits = get_json(
        f"{settings.FUEL_ROUTE['NOMINATIM_URL']}/search",
        params={"q": query, "countrycodes": "us", "format": "jsonv2", "limit": 1},
    )
    loc = None
    if hits:
        lat, lng = float(hits[0]["lat"]), float(hits[0]["lon"])
        if in_usa((lat, lng)):
            loc = Location(query, hits[0].get("display_name", query), lat, lng, "nominatim")
    cache.set(cache_key, loc or False)
    return loc
