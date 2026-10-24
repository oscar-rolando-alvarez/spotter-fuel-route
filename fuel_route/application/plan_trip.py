"""PlanTrip use case (application service) and its caching decorator.

Orchestrates the ports in a fixed pipeline; owns no I/O and no framework code:

    resolve start/finish -> route (1 external call) -> corridor search -> strategy -> stops

Dependencies are injected by the composition root (fuel_route/container.py).
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace

from fuel_route.domain.geo import simplify
from fuel_route.domain.model import Candidate, FuelStop, Route, TripPlan, Vehicle
from fuel_route.domain.ports import (
    Cache,
    CorridorFinder,
    LocationResolver,
    RefuelStrategy,
    RoutingProvider,
    StationRepository,
)

from .metering import metered
from .singleflight import SingleFlight

# ~100 m. The plan keeps only this display geometry: simplifying a 35k-vertex route costs
# ~37 ms, so it is done once per computed plan, never per response (see load-test report).
DISPLAY_TOLERANCE_DEG = 0.001


class _DisplayGeometry:
    """Memoizes route simplification per route (it depends on nothing else).

    Under load, many plans share a route (different fuel or penalty, same trip); without
    this, simplification was ~40% of the compute path. Small bounded LRU, thread-safe.
    """

    def __init__(self, maxsize: int = 512):
        self._items: OrderedDict[tuple, Route] = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def __call__(self, route: Route) -> Route:
        c = route.coordinates
        key = (c[0], c[-1], len(c), route.distance_miles) if c else ()
        with self._lock:
            if (hit := self._items.get(key)) is not None:
                self._items.move_to_end(key)
                return hit
        display = replace(route, coordinates=tuple(simplify(c, DISPLAY_TOLERANCE_DEG)))
        with self._lock:
            self._items[key] = display
            if len(self._items) > self._maxsize:
                self._items.popitem(last=False)
        return display


@dataclass(frozen=True)
class PlanTripCommand:
    start: str
    finish: str
    start_fuel_gallons: float | None = None  # None = full tank
    stop_penalty: float | None = None  # None = configured default
    strategy: str = "dp"


class _Stopwatch:
    def __init__(self):
        self.laps: dict[str, float] = {}
        self._t0 = self._last = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.laps[name] = round((now - self._last) * 1000, 1)
        self._last = now

    @property
    def total_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 1)


class PlanTripService:
    def __init__(
        self,
        *,
        locations: LocationResolver,
        router: RoutingProvider,
        corridor: CorridorFinder,
        stations: StationRepository,
        strategy_factory: Callable[[str, float], RefuelStrategy],
        vehicle: Vehicle,
        corridor_miles: float,
        default_stop_penalty: float,
    ):
        self._locations = locations
        self._router = router
        self._corridor = corridor
        self._stations = stations
        self._strategy_factory = strategy_factory
        self._vehicle = vehicle
        self._corridor_miles = corridor_miles
        self._default_stop_penalty = default_stop_penalty
        self._display = _DisplayGeometry()

    def execute(self, cmd: PlanTripCommand) -> TripPlan:
        vehicle = self._vehicle
        tank = vehicle.tank_gallons
        start_fuel = tank if cmd.start_fuel_gallons is None else min(cmd.start_fuel_gallons, tank)
        stop_penalty = self._default_stop_penalty if cmd.stop_penalty is None else cmd.stop_penalty
        strategy = self._strategy_factory(cmd.strategy, stop_penalty)  # fail fast, before any I/O

        with metered() as calls:
            clock = _Stopwatch()
            start = self._locations.resolve(cmd.start)
            finish = self._locations.resolve(cmd.finish)
            clock.lap("geocode")
            route = self._router.route(start.point, finish.point)
            clock.lap("routing")
            hits = self._corridor.along_route(route.coordinates, self._corridor_miles)
            clock.lap("corridor")
            fuel = strategy.plan(
                [Candidate(h.station.id, h.route_mile, h.station.price) for h in hits],
                route.distance_miles,
                vehicle,
                start_fuel,
            )
            clock.lap("optimize")

            offsets = {h.station.id: h.offset_miles for h in hits}
            details = self._stations.details(p.candidate.key for p in fuel.purchases)
            stops = [
                FuelStop(n, p, offsets[p.candidate.key], details[p.candidate.key])
                for n, p in enumerate(fuel.purchases, start=1)
            ]
            # Full resolution was only needed for the corridor search; keep the light version.
            display_route = self._display(route)
            clock.lap("simplify")
            return TripPlan(
                start=start,
                finish=finish,
                route=display_route,
                vehicle=vehicle,
                start_fuel_gallons=start_fuel,
                strategy=strategy.name,
                stop_penalty=stop_penalty if strategy.name == "dp" else 0.0,
                fuel=fuel,
                stops=stops,
                stations_in_corridor=len(hits),
                corridor_miles=self._corridor_miles,
                external_api_calls=calls.get(),
                elapsed_ms=clock.total_ms,
                timings_ms=clock.laps,
            )


class CachedPlanTripService:
    """Decorator over the use case: identical commands are answered from cache (ADR-0007)."""

    def __init__(self, inner: PlanTripService, cache: Cache, ttl_seconds: int, dataset_version: Callable[[], str]):
        self._inner, self._cache, self._ttl = inner, cache, ttl_seconds
        self._dataset_version = dataset_version
        self._flight = SingleFlight()

    def execute(self, cmd: PlanTripCommand) -> TripPlan:
        normalized = {k: v.strip().lower() if isinstance(v, str) else v for k, v in asdict(cmd).items()}
        # Namespaced by dataset version: reloading prices implicitly invalidates every plan.
        raw = json.dumps([self._dataset_version(), normalized], sort_keys=True)
        key = "plan:" + hashlib.sha1(raw.encode()).hexdigest()
        t0 = time.perf_counter()
        if (hit := self._cache.get(key)) is not None:
            return self._as_hit(hit, t0)

        computed: list[TripPlan] = []

        def compute() -> TripPlan:
            plan = self._inner.execute(cmd)
            self._cache.set(key, plan, self._ttl)
            computed.append(plan)
            return plan

        # Concurrent identical misses wait for one computation instead of stampeding.
        plan = self._flight.do(key, lambda: self._cache.get(key), compute)
        return plan if computed else self._as_hit(plan, t0)

    @staticmethod
    def _as_hit(plan: TripPlan, t0: float) -> TripPlan:
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        return replace(plan, cache_hit=True, external_api_calls=0, elapsed_ms=elapsed, timings_ms={})
