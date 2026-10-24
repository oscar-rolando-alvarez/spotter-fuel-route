"""The use case tested through its ports with in-memory fakes: no DB, no HTTP, no Django views."""

import pytest
from django.core.cache import cache

from fuel_route.application.metering import record_external_call
from fuel_route.application.plan_trip import CachedPlanTripService, PlanTripCommand, PlanTripService
from fuel_route.domain.errors import NoFeasiblePlanError, UnknownStrategyError
from fuel_route.domain.model import Location, Route, StationDetails, StationPoint, Vehicle
from fuel_route.domain.optimizer import make_strategy
from fuel_route.infrastructure.station_index import GridStationIndex

LINE = tuple((40.0, -100.0 + i * 0.1) for i in range(121))  # ~636 mi east along 40N
POINTS = [StationPoint(1, 40.0, -99.0, 3.50), StationPoint(2, 40.0, -95.0, 2.90), StationPoint(3, 40.0, -92.0, 3.60)]


class FakeLocations:
    def __init__(self):
        self.queries = []

    def resolve(self, query):
        self.queries.append(query)
        lng = -100.0 if "west" in query.lower() else -88.0
        return Location(query, query.title(), 40.0, lng, "fake")


class FakeRouter:
    def __init__(self):
        self.calls = 0

    def route(self, start, finish):
        self.calls += 1
        record_external_call()  # behaves like a real network adapter
        return Route(636.0, 10.6, LINE)


class FakeStations:
    version = "v1"

    def all_points(self):
        return POINTS

    def details(self, ids):
        return {i: StationDetails(i, 1000 + i, f"Stop {i}", "", "Town", "NE", 40.0, -95.0) for i in ids}

    def count(self):
        return len(POINTS)

    def dataset_version(self):
        return self.version


@pytest.fixture
def parts():
    locations, router, stations = FakeLocations(), FakeRouter(), FakeStations()
    service = PlanTripService(
        locations=locations,
        router=router,
        corridor=GridStationIndex(POINTS),
        stations=stations,
        strategy_factory=make_strategy,
        vehicle=Vehicle(range_miles=500, mpg=10),
        corridor_miles=10,
        default_stop_penalty=5,
    )
    return service, locations, router, stations


def test_orchestrates_ports_into_a_trip_plan(parts):
    service, locations, router, _ = parts
    plan = service.execute(PlanTripCommand("West, NE", "East, IL"))

    assert locations.queries == ["West, NE", "East, IL"]
    assert router.calls == 1 and plan.external_api_calls == 1
    assert [s.station.opis_id for s in plan.stops] == [1002]  # the $2.90 station
    assert plan.strategy == "dp" and plan.stop_penalty == 5
    assert plan.start_fuel_gallons == 50
    assert set(plan.timings_ms) == {"geocode", "routing", "corridor", "optimize", "simplify"}
    assert len(plan.route.coordinates) == 2  # straight line: simplified to its endpoints


def test_unknown_strategy_fails_before_any_io(parts):
    service, locations, router, _ = parts
    with pytest.raises(UnknownStrategyError):
        service.execute(PlanTripCommand("West, NE", "East, IL", strategy="nope"))
    assert locations.queries == [] and router.calls == 0


def test_partial_tank_and_infeasible_plan(parts):
    service, *_ = parts
    with pytest.raises(NoFeasiblePlanError):
        service.execute(PlanTripCommand("West, NE", "East, IL", start_fuel_gallons=1))


def test_cached_decorator_serves_hits_and_namespaces_by_dataset_version(parts, db):
    service, _, router, stations = parts
    cached = CachedPlanTripService(service, cache, 60, stations.dataset_version)
    cmd = PlanTripCommand("West, NE", "East, IL")

    first, second = cached.execute(cmd), cached.execute(PlanTripCommand(" west, ne ", "EAST, IL"))
    assert (first.cache_hit, second.cache_hit) == (False, True)
    assert second.external_api_calls == 0 and router.calls == 1

    stations.version = "v2"
    assert cached.execute(cmd).cache_hit is False
    assert router.calls == 2
