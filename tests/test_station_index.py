import math

from fuel_route.domain.model import StationPoint
from fuel_route.infrastructure.station_index import GridStationIndex, LazyStationIndex

LINE = [(40.0, -100.0 + i * 0.1) for i in range(101)]  # 100W -> 90W along 40N, ~530 mi


def test_finds_stations_in_corridor_with_route_mile():
    stations = [
        StationPoint(1, 40.05, -99.0, 3.0),  # ~3.5 mi off route, ~53 mi in
        StationPoint(2, 40.0, -95.0, 3.1),  # on route, ~265 mi in
        StationPoint(3, 41.0, -95.0, 2.0),  # 69 mi off route
        StationPoint(4, 40.0, -80.0, 2.0),  # beyond the end
    ]
    hits = GridStationIndex(stations).along_route(LINE, corridor_miles=10)
    assert [h.station.id for h in hits] == [1, 2]
    assert math.isclose(hits[0].route_mile, 53, abs_tol=1.5)
    assert math.isclose(hits[0].offset_miles, 3.5, abs_tol=0.5)
    assert math.isclose(hits[1].route_mile, 265, abs_tol=1.5)


def test_wide_corridor_searches_more_cells():
    stations = [StationPoint(1, 40.4, -95.0, 3.0)]  # ~28 mi north: more than one 0.25° cell away
    index = GridStationIndex(stations)
    assert index.along_route(LINE, corridor_miles=10) == []
    assert len(index.along_route(LINE, corridor_miles=30)) == 1


class FakeRepository:
    def __init__(self):
        self.version = "v1"
        self.points = [StationPoint(1, 40.0, -95.0, 3.0)]
        self.loads = 0

    def all_points(self):
        self.loads += 1
        return list(self.points)

    def dataset_version(self):
        return self.version


def test_lazy_proxy_builds_once_and_rebuilds_on_new_dataset_version():
    repo = FakeRepository()
    proxy = LazyStationIndex(repo)
    assert repo.loads == 0  # nothing built until first use
    assert proxy.size == 1 and proxy.size == 1
    assert repo.loads == 1

    repo.points.append(StationPoint(2, 40.0, -94.0, 2.9))
    repo.version = "v2"  # prices reloaded by another process
    assert len(proxy.along_route(LINE, 10)) == 2
    assert repo.loads == 2
