"""CorridorFinder adapters: an in-memory uniform grid, behind a lazy Virtual Proxy (ADR-0005).

~6.6k stations fit comfortably in memory. They are bucketed into fixed lat/lng cells
once per process; a corridor query then only touches the cells around each resampled
route point instead of scanning every station for every point.
"""

import math
import threading
from collections import OrderedDict, defaultdict
from collections.abc import Sequence

from fuel_route.domain.geo import haversine_miles, resample
from fuel_route.domain.model import CorridorHit, LatLng, StationPoint
from fuel_route.domain.ports import StationRepository

CELL_DEG = 0.25  # ~17 mi of latitude; _ring() widens the search for wider corridors
RESAMPLE_MILES = 1.0  # projection error <= 0.5 mi, far below station geocoding error


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return math.floor(lat / CELL_DEG), math.floor(lng / CELL_DEG)


class GridStationIndex:
    def __init__(self, stations: Sequence[StationPoint]):
        self._size = len(stations)
        self._grid: dict[tuple[int, int], list[StationPoint]] = defaultdict(list)
        for s in stations:
            self._grid[_cell(s.lat, s.lng)].append(s)

    @property
    def size(self) -> int:
        return self._size

    @staticmethod
    def _ring(lat: float, corridor_miles: float) -> tuple[int, int]:
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


class LazyStationIndex:
    """Virtual Proxy: builds the grid from the repository on first use, thread-safely.

    It also rebuilds when the dataset version in the database changes, so prices
    reloaded by the management command (another process) reach every web worker
    without a restart. The version check is one indexed single-row query.

    Corridor results are memoized per (route, corridor width) in a bounded LRU that is
    dropped with the grid on a version change: the stations near a route depend only on
    the route and the loaded data, not on fuel level or stop penalty (ADR-0013).
    """

    def __init__(self, repository: StationRepository, memo_size: int = 256):
        self._repository = repository
        self._index: GridStationIndex | None = None
        self._version: str | None = None
        self._lock = threading.Lock()
        self._memo: OrderedDict[tuple, list[CorridorHit]] = OrderedDict()
        self._memo_size = memo_size

    def _get(self) -> GridStationIndex:
        version = self._repository.dataset_version()
        if self._index is None or version != self._version:
            with self._lock:
                if self._index is None or version != self._version:
                    # A version/points race only causes one extra rebuild, never stale data.
                    self._index = GridStationIndex(self._repository.all_points())
                    self._version = version
                    self._memo.clear()
        return self._index

    @property
    def size(self) -> int:
        return self._get().size

    def along_route(self, route: Sequence[LatLng], corridor_miles: float) -> list[CorridorHit]:
        index = self._get()
        # Cheap fingerprint of the polyline (endpoints, midpoint, vertex count) + width.
        key = (route[0], route[len(route) // 2], route[-1], len(route), corridor_miles) if route else ()
        with self._lock:
            if (hit := self._memo.get(key)) is not None:
                self._memo.move_to_end(key)
                return list(hit)
        hits = index.along_route(route, corridor_miles)
        with self._lock:
            if index is self._index:  # don't memoize results computed from a superseded grid
                self._memo[key] = hits
                if len(self._memo) > self._memo_size:
                    self._memo.popitem(last=False)
        return list(hits)
