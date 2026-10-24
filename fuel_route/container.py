"""Composition root: the one place that knows concrete classes and wires them to ports.

Built lazily once per process. Tests call ``reset()`` (or override settings first) to get
a freshly wired graph. No DI framework: a dozen lines of constructor injection is clearer
than a container library at this size (ADR-0002).
"""

import threading
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from fuel_route.application.plan_trip import CachedPlanTripService, PlanTripService
from fuel_route.domain.model import Vehicle
from fuel_route.domain.optimizer import make_strategy
from fuel_route.infrastructure.boundary import load_region
from fuel_route.infrastructure.caching import CachedGeocoder, CachedRoutingProvider
from fuel_route.infrastructure.geocoding import CoordinateGeocoder, GazetteerGeocoder, GeocoderChain, NominatimGeocoder
from fuel_route.infrastructure.http import JsonHttpClient
from fuel_route.infrastructure.osrm import OsrmRoutingProvider
from fuel_route.infrastructure.repositories import DjangoStationRepository
from fuel_route.infrastructure.station_index import LazyStationIndex


@dataclass(frozen=True)
class Container:
    plan_trip: CachedPlanTripService
    stations: DjangoStationRepository
    station_index: LazyStationIndex


_container: Container | None = None
_lock = threading.Lock()


def _build() -> Container:
    cfg = settings.FUEL_ROUTE
    ttl = cfg["CACHE_TTL_SECONDS"]
    http = JsonHttpClient(cfg["USER_AGENT"], cfg["HTTP_TIMEOUT_SECONDS"])

    usa = load_region(settings.DATA_DIR / "us_border.json.gz")
    geocoders = [CoordinateGeocoder(usa), GazetteerGeocoder()]
    if cfg["GEOCODER_FALLBACK"]:
        geocoders.append(CachedGeocoder(NominatimGeocoder(cfg["NOMINATIM_URL"], http, usa), cache, ttl))

    stations = DjangoStationRepository(version_ttl_seconds=cfg["DATASET_VERSION_TTL_SECONDS"])
    index = LazyStationIndex(stations)
    service = PlanTripService(
        locations=GeocoderChain(geocoders),
        router=CachedRoutingProvider(OsrmRoutingProvider(cfg["OSRM_URL"], http), cache, ttl),
        corridor=index,
        stations=stations,
        strategy_factory=make_strategy,
        vehicle=Vehicle(range_miles=cfg["VEHICLE_RANGE_MILES"], mpg=cfg["VEHICLE_MPG"]),
        corridor_miles=cfg["CORRIDOR_MILES"],
        default_stop_penalty=cfg["STOP_PENALTY_USD"],
    )
    return Container(CachedPlanTripService(service, cache, ttl, stations.dataset_version), stations, index)


def get_container() -> Container:
    global _container
    if _container is None:
        with _lock:
            if _container is None:
                _container = _build()
    return _container


def reset() -> None:
    """Drop the wired graph (tests use this after overriding settings)."""
    global _container
    with _lock:
        _container = None
