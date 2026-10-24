import threading
import time

from django.core.cache import cache

from fuel_route.domain.model import Location, Route
from fuel_route.infrastructure.caching import CachedGeocoder, CachedRoutingProvider


class CountingRouter:
    calls = 0

    def route(self, start, finish):
        self.calls += 1
        return Route(1.0, 1.0, (start, finish))


class CountingGeocoder:
    name = "counting"

    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def geocode(self, query):
        self.calls += 1
        return self.answer


def test_routing_decorator_is_transparent_and_calls_inner_once():
    inner = CountingRouter()
    router = CachedRoutingProvider(inner, cache, 60)
    a = router.route((40.0, -100.0), (41.0, -90.0))
    b = router.route((40.000001, -100.0), (41.0, -90.0))  # same to 5 decimals (~1 m)
    router.route((40.1, -100.0), (41.0, -90.0))
    assert a == b and inner.calls == 2


def test_geocoder_decorator_caches_misses_too():
    miss = CountingGeocoder(None)
    geocoder = CachedGeocoder(miss, cache, 60)
    assert geocoder.geocode("nowhere") is None and geocoder.geocode("NOWHERE ") is None
    assert miss.calls == 1

    hit = CountingGeocoder(Location("x", "X", 1.0, 2.0, "counting"))
    geocoder = CachedGeocoder(hit, cache, 60)
    assert geocoder.geocode("x") == geocoder.geocode("x") and hit.calls == 1


class SlowRouter:
    def __init__(self):
        self.calls = 0

    def route(self, start, finish):
        self.calls += 1
        time.sleep(0.05)  # an upstream call in flight while others arrive
        return Route(1.0, 1.0, (start, finish))


def test_concurrent_misses_make_a_single_upstream_call():
    inner = SlowRouter()
    router = CachedRoutingProvider(inner, cache, 60)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(router.route((40.0, -100.0), (41.0, -90.0)))) for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert inner.calls == 1 and len(results) == 20 and len(set(results)) == 1
