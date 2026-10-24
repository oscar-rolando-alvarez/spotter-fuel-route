"""Ports (hexagonal architecture): what the application needs from the outside world.

Adapters in ``fuel_route.infrastructure`` implement these structurally (PEP 544
Protocols, no inheritance needed). Tests swap them for in-memory fakes.
"""

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from .model import Candidate, CorridorHit, FuelPlan, LatLng, Location, Route, StationDetails, StationPoint, Vehicle


class Geocoder(Protocol):
    """One link of the geocoding chain: return a Location, or None to pass it on."""

    name: str

    def geocode(self, query: str) -> Location | None: ...


class Boundary(Protocol):
    """Geographic scope of the service (the USA): is this point inside it?"""

    def contains(self, point: LatLng) -> bool: ...


class LocationResolver(Protocol):
    """Resolve a query or raise LocationNotFoundError (the chain as a whole)."""

    def resolve(self, query: str) -> Location: ...


class RoutingProvider(Protocol):
    def route(self, start: LatLng, finish: LatLng) -> Route: ...


class StationRepository(Protocol):
    def all_points(self) -> list[StationPoint]: ...

    def details(self, ids: Iterable[int]) -> dict[int, StationDetails]: ...

    def count(self) -> int: ...

    def dataset_version(self) -> str: ...


class CorridorFinder(Protocol):
    """Spatial query: stations within ``corridor_miles`` of a polyline, by route mile."""

    @property
    def size(self) -> int: ...

    def along_route(self, route: Sequence[LatLng], corridor_miles: float) -> list[CorridorHit]: ...


class RefuelStrategy(Protocol):
    """Strategy pattern: interchangeable refuelling algorithms."""

    name: str

    def plan(
        self, candidates: Sequence[Candidate], total_miles: float, vehicle: Vehicle, start_fuel_gallons: float
    ) -> FuelPlan: ...


class Cache(Protocol):
    """Key-value cache (Django's cache API satisfies it)."""

    def get(self, key: str, default: Any = None) -> Any: ...

    def set(self, key: str, value: Any, timeout: int | None = ...) -> None: ...
