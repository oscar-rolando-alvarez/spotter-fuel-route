"""In-memory spatial grid over fuel stations, used to find stations along a route.

~6.7k stations fit comfortably in memory. They are bucketed into fixed lat/lng cells
once per process; a corridor query then only touches the handful of cells around
each resampled route point instead of scanning every station per point.
"""

import math
import threading
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .geo import LatLng, haversine_miles, resample

CELL_DEG = 0.25  # ~17 mi of latitude; must stay >= corridor width (see _ring)
RESAMPLE_MILES = 1.0


@dataclass(frozen=True, slots=True)
class StationPoint:
    id: int
    lat: float
    lng: float
    price: float


@dataclass(frozen=True, slots=True)
class CorridorHit:
    station: StationPoint
    route_mile: float
    offset_miles: float


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return math.floor(lat / CELL_DEG), math.floor(lng / CELL_DEG)


class StationIndex:
    def __init__(self, stations: Sequence[StationPoint]):
        self.size = len(stations)
        self._grid: dict[tuple[int, int], list[StationPoint]] = defaultdict(list)
        for s in stations:
            self._grid[_cell(s.lat, s.lng)].append(s)

    def _ring(self, lat: float, corridor_miles: float) -> tuple[int, int]:
        """How many cells to search around a point, in (lat, lng) directions."""
        lat_cells = math.ceil(corridor_miles / (CELL_DEG * 69.0))
        miles_per_lng_deg = max(69.17 * math.cos(math.radians(lat)), 1.0)
        lng_cells = math.ceil(corridor_miles / (CELL_DEG * miles_per_lng_deg))
        return lat_cells, lng_cells

    def along_route(self, route: Sequence[LatLng], corridor_miles: float) -> list[CorridorHit]:
        """Stations within ``corridor_miles`` of the route, sorted by route mile.

        Each station is projected onto the route at its closest resampled point, which
        gives its position (mile marker) for the refuelling algorithm.
        """
        best: dict[int, CorridorHit] = {}
        for point, mile in resample(route, RESAMPLE_MILES):
            ci, cj = _cell(*point)
            di, dj = self._ring(point[0], corridor_miles)
            for i in range(ci - di, ci + di + 1):
                for j in range(cj - dj, cj + dj + 1):
                    for s in self._grid.get((i, j), ()):
                        d = haversine_miles(point, (s.lat, s.lng))
                        if d <= corridor_miles and (s.id not in best or d < best[s.id].offset_miles):
                            best[s.id] = CorridorHit(s, mile, d)
        return sorted(best.values(), key=lambda h: (h.route_mile, h.station.price))


_index: StationIndex | None = None
_lock = threading.Lock()


def get_station_index() -> StationIndex:
    """Process-wide index, built lazily from the DB on first use."""
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                from fuel_route.models import FuelStation

                rows = FuelStation.objects.values_list("id", "lat", "lng", "price")
                _index = StationIndex([StationPoint(i, la, ln, float(p)) for i, la, ln, p in rows])
    return _index


def reset_station_index() -> None:
    """Drop the cached index (after reloading stations, or between tests)."""
    global _index
    with _lock:
        _index = None
