"""Caching as Decorators around ports (ADR-0007).

Each decorator implements the same port as the object it wraps, so callers can't tell
cached from uncached and caching policy stays out of the adapters and the use case.
"""

import hashlib

from fuel_route.application.singleflight import SingleFlight
from fuel_route.domain.model import LatLng, Location, Route
from fuel_route.domain.ports import Cache, Geocoder, RoutingProvider

_MISS = object()


def _key(prefix: str, raw: str) -> str:
    # Hash so keys are short and safe for any backend (memcached rejects spaces).
    return f"{prefix}:{hashlib.sha1(raw.encode()).hexdigest()}"


class CachedRoutingProvider:
    def __init__(self, inner: RoutingProvider, cache: Cache, ttl_seconds: int):
        self._inner, self._cache, self._ttl = inner, cache, ttl_seconds
        self._flight = SingleFlight()

    def route(self, start: LatLng, finish: LatLng) -> Route:
        # 5 decimals ≈ 1 m: identical inputs share a route, distinct places never collide.
        key = _key("route", f"{start[0]:.5f},{start[1]:.5f};{finish[0]:.5f},{finish[1]:.5f}")
        if (hit := self._cache.get(key)) is not None:
            return hit

        def fetch() -> Route:
            route = self._inner.route(start, finish)
            self._cache.set(key, route, self._ttl)
            return route

        # One upstream call per key even when many requests miss at the same moment.
        return self._flight.do(key, lambda: self._cache.get(key), fetch)


class CachedGeocoder:
    """Caches hits *and* misses (negative caching) so a bad query isn't re-sent upstream."""

    def __init__(self, inner: Geocoder, cache: Cache, ttl_seconds: int):
        self._inner, self._cache, self._ttl = inner, cache, ttl_seconds
        self.name = inner.name

    def geocode(self, query: str) -> Location | None:
        key = _key(f"geocode:{self.name}", query.strip().lower())
        if (hit := self._cache.get(key, _MISS)) is not _MISS:
            return hit
        loc = self._inner.geocode(query)
        self._cache.set(key, loc, self._ttl)
        return loc
