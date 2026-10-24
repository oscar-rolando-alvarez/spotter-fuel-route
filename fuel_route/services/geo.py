"""Small, dependency-free geometry helpers. Coordinates are (lat, lng) degrees."""

import math
from collections.abc import Sequence

EARTH_RADIUS_MILES = 3958.8
LatLng = tuple[float, float]

# Rough boxes for CONUS, Alaska and Hawaii; good enough to reject "Paris, France".
_US_BOXES = (
    (24.3, 49.5, -125.0, -66.8),
    (51.2, 71.5, -179.2, -129.9),
    (18.8, 22.4, -160.5, -154.6),
)


def haversine_miles(a: LatLng, b: LatLng) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def in_usa(point: LatLng) -> bool:
    lat, lng = point
    return any(s <= lat <= n and w <= lng <= e for s, n, w, e in _US_BOXES)


def cumulative_miles(points: Sequence[LatLng]) -> list[float]:
    """Distance from the first point to each point along the polyline."""
    out = [0.0]
    for prev, cur in zip(points, points[1:]):
        out.append(out[-1] + haversine_miles(prev, cur))
    return out


def resample(points: Sequence[LatLng], step_miles: float) -> list[tuple[LatLng, float]]:
    """Points spaced exactly ``step_miles`` apart along the polyline, plus the endpoint.

    Each item is ``(point, route_mile)``. Dense OSRM geometry (tens of thousands of
    vertices) becomes ~1 point per mile, which bounds the corridor search cost.
    """
    if not points:
        return []
    out = [(points[0], 0.0)]
    travelled = 0.0
    next_mark = step_miles
    for prev, cur in zip(points, points[1:]):
        seg = haversine_miles(prev, cur)
        while seg > 0 and travelled + seg >= next_mark:
            f = (next_mark - travelled) / seg
            out.append(((prev[0] + (cur[0] - prev[0]) * f, prev[1] + (cur[1] - prev[1]) * f), next_mark))
            next_mark += step_miles
        travelled += seg
    if out[-1][1] < travelled:
        out.append((points[-1], travelled))
    return out


def simplify(points: Sequence[LatLng], tolerance_deg: float) -> list[LatLng]:
    """Ramer–Douglas–Peucker, iterative (no recursion limit on 50k-vertex routes)."""
    n = len(points)
    if n < 3:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        (y1, x1), (y2, x2) = points[start], points[end]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        max_d, idx = 0.0, -1
        for i in range(start + 1, end):
            y0, x0 = points[i]
            d = math.hypot(x0 - x1, y0 - y1) if norm == 0 else abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
            if d > max_d:
                max_d, idx = d, i
        if max_d > tolerance_deg:
            keep[idx] = True
            stack.append((start, idx))
            stack.append((idx, end))
    return [p for p, k in zip(points, keep) if k]
