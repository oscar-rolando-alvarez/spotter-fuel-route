"""Domain model: immutable value objects and entities of the trip-planning domain.

Everything here is plain Python (no Django, no I/O) so the core can be reasoned
about, tested and reused without the framework. See docs/adr/0002.
"""

from dataclasses import dataclass, field

LatLng = tuple[float, float]  # (lat, lng) in degrees


@dataclass(frozen=True, slots=True)
class Vehicle:
    range_miles: float
    mpg: float

    @property
    def tank_gallons(self) -> float:
        return self.range_miles / self.mpg


@dataclass(frozen=True, slots=True)
class Location:
    """A user-supplied place resolved to coordinates."""

    query: str
    label: str
    lat: float
    lng: float
    source: str  # which geocoder in the chain resolved it

    @property
    def point(self) -> LatLng:
        return self.lat, self.lng


@dataclass(frozen=True, slots=True)
class Route:
    distance_miles: float
    duration_hours: float
    coordinates: tuple[LatLng, ...]  # full-resolution polyline


@dataclass(frozen=True, slots=True)
class StationPoint:
    """The minimal projection of a station the spatial index needs."""

    id: int
    lat: float
    lng: float
    price: float


@dataclass(frozen=True, slots=True)
class StationDetails:
    """Read model for presenting a chosen station."""

    id: int
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    lat: float
    lng: float


@dataclass(frozen=True, slots=True)
class CorridorHit:
    """A station within the corridor, projected onto the route."""

    station: StationPoint
    route_mile: float
    offset_miles: float


@dataclass(frozen=True, slots=True)
class Candidate:
    """Optimizer input: a station reduced to (position, price)."""

    key: int
    mile: float
    price: float


@dataclass(frozen=True, slots=True)
class Purchase:
    candidate: Candidate
    gallons: float
    cost: float
    fuel_on_arrival: float


@dataclass(frozen=True, slots=True)
class FuelPlan:
    purchases: list[Purchase]
    total_cost: float
    gallons_purchased: float
    gallons_consumed: float


@dataclass(frozen=True, slots=True)
class FuelStop:
    sequence: int
    purchase: Purchase
    offset_miles: float
    station: StationDetails


@dataclass(frozen=True, slots=True)
class TripPlan:
    """Aggregate returned by the PlanTrip use case."""

    start: Location
    finish: Location
    route: Route
    vehicle: Vehicle
    start_fuel_gallons: float
    strategy: str
    stop_penalty: float
    fuel: FuelPlan
    stops: list[FuelStop]
    stations_in_corridor: int
    corridor_miles: float
    external_api_calls: int = 0
    elapsed_ms: float = 0.0
    timings_ms: dict[str, float] = field(default_factory=dict)
    cache_hit: bool = False
