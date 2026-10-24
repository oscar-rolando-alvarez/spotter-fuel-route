# ADR-0012: Performance under load: precompute display geometry, single-flight caches, shed load at the edge

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez
- **Amends:** ADR-0007 (caching) and ADR-0009 (the presenter no longer simplifies geometry)
- **Evidence:** [`docs/load-test-report.md`](../load-test-report.md)

## Context and problem statement

The first production-like load test (gunicorn with 8 workers × 4 threads, fake OSRM at 250 ms) gave **197 RPS with p50 = 1.1 s on fully cached requests**, where a cache hit should cost milliseconds. Profiling showed two design flaws and one operational gap:

1. **Per-response work that belonged to the computation.** The presenter ran Douglas–Peucker on the full 35k-vertex route for every response (37 ms), and the cached `TripPlan` carried the full-resolution route (a 688 KB pickle on every cache get).
2. **Cache stampede.** Concurrent misses on the same key each called OSRM, which violates the one-call budget (ADR-0003) exactly when traffic peaks.
3. **No overload behaviour.** At saturation, cheap endpoints (`/health`, 400s) queued behind expensive ones, and connection storms produced TCP resets.

## Decision drivers

- Cache hits must be O(response size), not O(route size).
- The external-call budget must hold under concurrency, not only sequentially.
- Overload should degrade predictably, never into crashes or wrong answers.
- No new infrastructure for the assessment. Production recommendations should be explicit.

## Considered options

1. **Cache the rendered JSON bytes** per command.
2. **Precompute the display geometry in the use case**, keep only that in the `TripPlan`, and memoize it per route.
3. Speed up Douglas–Peucker (numpy/C) but keep it per response.

For the stampede:

4. **Per-process single-flight** (per-key lock plus a re-check) in the cache decorators.
5. A distributed lock in Redis (`SET NX PX`).
6. Do nothing, and accept N calls on a cold burst.

For overload:

7. **Application-level load shedding** middleware.
8. **Edge load shedding** (proxy or load balancer) plus probe isolation plus autoscaling.

## Decision outcome

**Chosen: 2, 4 and 8.**

- **2. Precompute and memoize.** `PlanTripService` simplifies after the corridor search, which still uses full resolution, and stores only the display route in the `TripPlan`. A thread-safe LRU of 512 routes, keyed by (first point, last point, vertex count, distance), memoizes simplification per route. The presenter only reorders coordinates. Measured: the cache hit plus presentation dropped from **40.4 ms to 0.31 ms**, and the cached plan from **688 KB to 35 KB**.
  - Rendered-JSON caching (option 1) was rejected because it couples the cache to the wire format and to `map_url`, which is host-dependent, and because it would not help the compute path. Option 2 helps both.
- **4. `SingleFlight`.** It lives in `application/singleflight.py` and is used by `CachedRoutingProvider` and `CachedPlanTripService`. Concurrent misses for a key wait for one computation, and the locks are dropped when idle so memory stays bounded. Across processes the worst case is one upstream call per worker, which is acceptable. Option 5 (Redis lock) is the upgrade once Redis is introduced (ADR-0011).
- **8. Shed load at the edge, not in Django.** Application middleware (option 7) cannot see requests queued in the socket backlog or the gunicorn queue, which is where the latency builds up. It would only shed what has already waited. The proxy can bound concurrency and return a fast `503` with `Retry-After`. Probes are served by the proxy or a separate worker, and autoscaling triggers on p95 latency or on CPU above about 70%. Linux `net.core.somaxconn` should be ≥ 4096.

### Consequences

- 👍 Warm path: **197 → 2,277 RPS (11.5×)**, p50 1,100 → 76 ms. Compute path: **90 → 140 RPS (+55%)**.
- 👍 The one-call budget now holds under concurrency, which is tested with 20 threads.
- 👍 There were 0 incorrect responses across about 356k validated requests, including spikes of 2,000 users.
- 👎 The `TripPlan` no longer carries the full-resolution route. A future feature needing it, such as elevation profiles, must request it explicitly or re-fetch it from the routing cache.
- 👎 The memo key is a cheap fingerprint, not a full hash. A collision would need the same endpoints, vertex count and distance with a different path, which is negligible for road routes.
- ⚖️ Overload protection is a deployment responsibility. It is documented here and in ADR-0011, not enforced in code.

### Confirmation

- `tests/test_caching.py::test_concurrent_misses_make_a_single_upstream_call`.
- `tests/test_plan_trip_service.py` checks that the plan's geometry is the simplified one and that `timings_ms` includes `simplify`.
- `loadtest/run_all.sh` reproduces the report. Its Locust scenarios fail any response with a wrong cost, broken invariants or more than 1 external call.

## Revisit when

- Redis is introduced. Upgrade single-flight to a distributed lock for cross-worker deduplication.
- The p95 SLO tightens below about 150 ms at more than 500 RPS per node. Profile the corridor search, which is now the largest compute stage (about 20 ms), and consider PostGIS or a vectorized grid (ADR-0005).
