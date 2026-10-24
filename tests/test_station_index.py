import math

from fuel_route.services.station_index import StationIndex, StationPoint

LINE = [(40.0, -100.0 + i * 0.1) for i in range(101)]  # 100W -> 90W along 40N, ~530 mi


def test_finds_stations_in_corridor_with_route_mile():
    stations = [
        StationPoint(1, 40.05, -99.0, 3.0),  # ~3.5 mi off route, ~53 mi in
        StationPoint(2, 40.0, -95.0, 3.1),  # on route, ~265 mi in
        StationPoint(3, 41.0, -95.0, 2.0),  # 69 mi off route
        StationPoint(4, 40.0, -80.0, 2.0),  # beyond the end
    ]
    hits = StationIndex(stations).along_route(LINE, corridor_miles=10)
    assert [h.station.id for h in hits] == [1, 2]
    assert math.isclose(hits[0].route_mile, 53, abs_tol=1.5)
    assert math.isclose(hits[0].offset_miles, 3.5, abs_tol=0.5)
    assert math.isclose(hits[1].route_mile, 265, abs_tol=1.5)


def test_wide_corridor_searches_more_cells():
    stations = [StationPoint(1, 40.4, -95.0, 3.0)]  # ~28 mi north: more than one 0.25° cell away
    index = StationIndex(stations)
    assert index.along_route(LINE, corridor_miles=10) == []
    assert len(index.along_route(LINE, corridor_miles=30)) == 1
