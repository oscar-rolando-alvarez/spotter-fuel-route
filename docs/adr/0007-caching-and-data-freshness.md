# ADR-0007: Caching as Decorators over ports, invalidated by a dataset version

- **Status:** Accepted. Amended by [ADR-0012](0012-performance-under-load.md), which adds single-flight to the decorators, and by [ADR-0013](0013-corridor-memo-and-http-caching.md), which adds HTTP conditional GET and a 1 s per-process cache of the dataset version.
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

The assignment rewards responses that are "as fast as possible" with minimal external calls. Three results are deterministic and worth caching:

| What | Deterministic on | Cost if recomputed |
|---|---|---|
| Route geometry | (start, finish) coordinates | 1 external call, 0.2–1.4 s |
| Free-text geocode | the query string | 1 external call, ~0.4–0.8 s |
| Whole trip plan | the command **and the price file** | ~1.5 s cold, ~80 ms warm |

The difficulty is **freshness**. Prices are reloaded by a management command running **in another process**. An in-process "clear cache" call would never reach the running web workers, which would keep serving plans and an index built from old prices.

## Decision drivers

- Keep caching *out of* the adapters and the use case (single responsibility), so each can be tested uncached.
- There must be no path that serves stale prices after a reload.
- It must work unchanged with a shared cache such as Redis and multiple workers.
- Cache keys must be safe for any backend. Memcached rejects spaces and long keys.

## Considered options

1. Cache inside each adapter, and inside the view.
2. **Decorators** implementing the same port as the wrapped object, with **dataset-version namespacing** for anything that depends on prices.
3. HTTP caching (`Cache-Control`, ETags) at a reverse proxy.
4. Explicit invalidation: the loader deletes keys or flushes the cache.

## Decision outcome

**Chosen: option 2.**

| Decorator | Wraps (port) | Key | Notes |
|---|---|---|---|
| `CachedRoutingProvider` | `RoutingProvider` | `route:sha1(lat,lng;lat,lng @ 5 dp)` | 5 dp ≈ 1 m: same place, same key |
| `CachedGeocoder` | `Geocoder` (Nominatim link) | `geocode:nominatim:sha1(normalized query)` | **Caches misses too** (negative caching), so bad input is not re-sent upstream |
| `CachedPlanTripService` | the use case | `plan:sha1([dataset_version, normalized command])` | A hit returns `cache_hit=true`, `external_api_calls=0` |

**Freshness by versioning, not invalidation.**
- `load_fuel_data` writes `FuelDataset.version = sha256(csv)` inside the same transaction as the new stations.
- The plan-cache key includes that version, so a reload makes every old plan key unreachable at once, in every process. Old entries expire through their TTL.
- `LazyStationIndex` (ADR-0005) compares the same version and rebuilds its grid.
- Routes and geocodes are **not** versioned, because they don't depend on prices.

Further details:
- The TTL is `CACHE_TTL_SECONDS`, 24 h by default.
- The backend is Django's cache: LocMem in development, and Redis in production with a settings-only change.
- The application layer depends on a `Cache` **port** (a Protocol with get and set), not on `django.core.cache`. The fitness test enforces this (ADR-0002).

### Consequences

- 👍 A repeat trip takes about 2 ms with 0 external calls. A new trip between already-routed points skips OSRM.
- 👍 Stale reads are impossible after a reload, with no coordination between processes and no cache flush, and it works across N workers and a shared Redis.
- 👍 Every decorator is independently tested and transparent to its caller.
- 👎 Old versions keep occupying cache memory until their TTL ends. This is acceptable: plans are small and reloads are rare (daily at most).
- 👎 Each request does one indexed single-row query to read the version. That costs about 0.1 ms, negligible next to the rest of the work.
- ⚖️ LocMem is per process. Hit rates rise with a shared cache, which ADR-0011 covers.

### Confirmation

- `tests/test_caching.py`: the routing decorator calls its inner provider once per distinct (rounded) key, and the geocoder decorator caches both hits and misses.
- `tests/test_plan_trip_service.py::test_cached_decorator_serves_hits_and_namespaces_by_dataset_version` covers hits, input normalization (`" west, ne "` is the same as `"West, NE"`) and the miss after a version bump.
- `tests/test_api.py::test_reloading_prices_invalidates_cached_plans` is the end-to-end check: a price update plus a new dataset version yields the new price on the next request.

## Pros and cons of the options

**Option 1, caching inside the adapters.** 👎 Mixes concerns. Uncached behaviour becomes hard to test. The policy is spread across files.

**Option 2, decorators plus version namespacing.** 👍 Single responsibility, testable, correct across processes. 👎 One extra lookup per request.

**Option 3, HTTP caching.** 👍 Needs no application code. 👎 Cannot cache *partial* results (route or geocode), and is invalidated by the URL rather than by data.

**Option 4, explicit invalidation.** 👎 Hard to make correct across processes: it needs pub/sub or a shared cache, and it is easy to forget a key family.

## Revisit when

- Prices arrive as a stream (per station, intra-day) rather than as a file. Move to per-station versions, or drop plan caching and keep only route caching.
- The cache memory budget becomes tight. Lower the TTL, or add LRU eviction (Redis `allkeys-lru`).
