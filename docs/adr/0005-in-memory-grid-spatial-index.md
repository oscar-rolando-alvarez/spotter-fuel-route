# ADR-0005: In-memory uniform-grid spatial index behind a lazy, version-aware proxy

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

For each trip we must find every station within *d* miles of a route polyline, and assign each one a **mile marker** (its position along the route) for the optimizer. Typical sizes:

- 6,626 stations;
- a coast-to-coast route with about 20k vertices and about 2,800 miles;
- 300 to 460 candidate stations come back.

A naive loop over every station and every vertex is about 1.3×10⁸ distance computations, which takes seconds. The target is under 100 ms for all local compute.

## Decision drivers

- p50 local compute under 100 ms on commodity hardware, in pure Python.
- No mandatory native or geo dependencies for reviewers. GDAL, GEOS and PostGIS are hard to install.
- Correct projection to a route mile.
- Data refreshes (ADR-0008) must reach running workers without restarts.

## Considered options

1. **PostGIS:** `ST_DWithin(station.geom, route_line, d)`, plus `ST_LineLocatePoint` for the mile marker.
2. **A KD-tree** (`scipy.spatial.cKDTree`) over station coordinates, with a radius query per resampled route point.
3. **An R-tree** (`rtree` / libspatialindex) over the route's segment bounding boxes.
4. **A uniform lat/lng grid** (spatial hash) in pure Python, queried at route points resampled every mile.
5. **Geohash prefixes** stored in the database and queried with `LIKE`.

## Decision outcome

**Chosen: option 4, a uniform grid,** implemented as `GridStationIndex` behind the `CorridorFinder` port and wrapped in a **Virtual Proxy** (`LazyStationIndex`).

### Algorithm

1. Bucket stations into 0.25° × 0.25° cells, about 17 × 13 miles at 40°N. This happens once per process in O(n).
2. Resample the route polyline to one point per mile. The projection error is ≤0.5 mi, well below the city-centroid error (ADR-0004), and it bounds the work by route length rather than vertex count.
3. For each point, scan only the neighbouring cells. The ring size is computed from the corridor width and the latitude, because longitude degrees shrink with cos(lat), so any corridor width stays correct.
4. Keep each station's **closest approach**. That point's cumulative distance is the station's route mile, and the distance itself is the reported offset.

**Measured:** 20 to 60 ms for 800 to 3,300-mile routes, with 113 to 460 hits.

### Virtual Proxy (`LazyStationIndex`)

- The grid is built on first use and not at import time, which keeps `manage.py` commands and the test startup cheap.
- It is thread-safe, using double-checked locking.
- **It is version-aware.** On each query it reads `FuelDataset.version`, a single-row primary-key lookup, and rebuilds the grid when the version changes. Prices reloaded by the management command, in another process, therefore reach every web worker without a restart (ADR-0007).

### Consequences

- 👍 Pure Python, zero native dependencies, and meets the latency budget.
- 👍 Memory use is trivial: about 6.6k small frozen dataclasses, under 2 MB per worker.
- 👍 The port allows a PostGIS implementation later without touching the use case or the tests of the optimizer.
- 👎 The index is per process. N workers hold N copies, which is acceptable at this size. In exchange, each worker rebuilds independently after a reload, costing about 50 ms once.
- 👎 Grid cells are not equal-area. Cell density rises toward the north, but the ring computation keeps the results correct; only the work per query changes slightly.
- ⚖️ Detour distance to the station is not added to the route. The 10-mile corridor bounds the error. This is documented in the README.

### Confirmation

- `tests/test_station_index.py`:
  - stations in and out of the corridor, with route mile and offset tolerances;
  - wider corridors search more cells;
  - the lazy proxy builds once and rebuilds on a new dataset version.
- `meta.timings_ms.corridor` is reported on every response.

## Pros and cons of the options

| Option | Latency | Setup burden | Projection to route mile | Notes |
|---|---|---|---|---|
| PostGIS | ~10 ms | High (GDAL/GEOS/PostGIS) | Native (`ST_LineLocatePoint`) | Best for production at scale |
| KD-tree (scipy) | ~10 ms | Medium (numpy/scipy wheels) | Manual | A heavy dependency for one query |
| R-tree | ~10 ms | Medium (libspatialindex) | Manual | Same |
| **Uniform grid** | 20–60 ms | **None** | Manual (resampling) | ✅ Chosen |
| Geohash in DB | 50–200 ms | Low | Manual | Many DB round trips; edge effects at prefix boundaries |

## Revisit when

- The station count grows past about 100k (all US retail stations), or several services need the same spatial queries. Move to PostGIS with an `ST_DWithin` plus `ST_LineLocatePoint` adapter implementing `CorridorFinder`.
- Detour-aware costing is required. Use OSRM's `table` service for the top-k candidates only, keeping the external-call budget explicit.
