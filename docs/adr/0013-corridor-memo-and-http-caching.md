# ADR-0013: Memoize corridors per route, add HTTP conditional GET, make compression configurable

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez
- **Amends:** ADR-0007 (adds HTTP-level caching, which ADR-0007 had considered only as an alternative, and a bounded staleness window for the dataset version) and ADR-0012 (updated capacity)
- **Evidence:** [`docs/load-test-report.md`](../load-test-report.md), round 2

## Context and problem statement

After ADR-0012, the profile of the compute path, where the plan cache misses, was:
- corridor search, about 20 to 60 ms;
- the DP, about 10 to 22 ms;
- framework overhead.

The corridor result depends **only on the route and the loaded dataset**, not on the starting fuel or the stop penalty, yet it was recomputed for every distinct command.

On the warm path, every repeat request still traversed Django, read the cache and rendered about 44 KB of JSON. Responses are deterministic, so most of that work can be skipped entirely when clients or a CDN revalidate.

Finally, each request read the dataset version from the database up to three times: for the plan-cache key, for the index check and for the new ETag.

## Decision drivers

- Remove work that does not depend on the request, at the layer that owns the data.
- Let clients and CDNs avoid the backend for repeats, without risking stale prices.
- Make every optimization measurable, and reversible where it is a trade-off.

## Decision outcome

1. **Corridor memoization in `LazyStationIndex`.**
   - A bounded LRU of 256 entries, keyed by a cheap fingerprint of the polyline (first point, middle point, last point, vertex count) plus the corridor width.
   - It is **cleared together with the grid when the dataset version changes**. The proxy already owns that version, so no stale corridor can survive a price reload.
   - Results computed from a grid that was superseded mid-flight are not stored.
2. **HTTP conditional GET on `GET /api/v1/route-plan/`** (`api/http_cache.py`).
   - The weak ETag is the SHA-256 of: the representation version, the dataset version, the normalized command, the vehicle and corridor settings, and the request host (because `map_url` embeds the host).
   - `If-None-Match` is evaluated **before** the use case runs. A match returns `304` with no body, after only serializer validation and a version read.
   - `Cache-Control: public, max-age=300, stale-while-revalidate=60`: five minutes of freshness for intermediaries, after which they revalidate cheaply. POST responses carry no cache headers.
3. **Gzip is configurable** with `GZIP_RESPONSES`, on by default. NYC→LA shrinks from 43.6 KB to 16.5 KB (2.6×), but compressing in Python costs about 15–25% of warm-path throughput. Behind nginx, CloudFront or an ALB, turn it off and let the edge compress.
4. **Dataset-version reads are cached per process** with `DATASET_VERSION_TTL_SECONDS` (default 1 s). This bounds staleness after a price reload to one second per worker and turns about 3 queries per request into about 1 query per second per worker.

### Results (same harness as ADR-0012; default configuration, gzip on)

| Scenario | Before (round 1) | After (round 2) | Change |
|---|---|---|---|
| Compute path, 100 users | 140 RPS, p95 1.7 s | **290 RPS, p95 890 ms** | 2.1× |
| Mixed at 100 users | 513 RPS, p95 480 ms | **907 RPS, p95 160 ms** | 1.8×, with 3× lower p95 |
| Capacity knee (p95 ≤ 160 ms) | ~490 RPS | **~900 RPS** | 1.85× |
| 2,000-user spike (200/s) | 553 RPS, 0.04% resets | **953 RPS, 0 errors** | 1.7× |
| Revalidation (304), 300 users | n/a | **6,289 RPS, p95 55 ms** | new |
| Warm 200s, 300 users | 2,277 RPS | 2,087 (gzip) / **2,710 (no gzip)** | the gzip trade-off is explicit |
| Cold, no cache | 95 RPS | **134 RPS** | +41% |

### Consequences

- 👍 Capacity per node nearly doubles at the same p95. CDNs and browsers can serve repeats with zero backend work.
- 👍 Every cache is versioned or bounded, so correctness under a price reload is preserved. Tests cover the ETag changing with the dataset version, and the corridor memo being dropped on a version change.
- 👎 **Freshness:** after a price reload, a worker may serve the previous version for up to `DATASET_VERSION_TTL_SECONDS` (1 s), and an intermediary for up to `max-age` (300 s) before it revalidates. Both are tunable, and acceptable for prices that change daily at most.
- 👎 The corridor memo key is a fingerprint, not a full hash (see ADR-0012 for why a collision is negligible).
- ⚖️ In-app gzip trades CPU for bandwidth. The default favours real networks, and the switch exists for proxy deployments.

### Confirmation

- `tests/test_api.py::test_conditional_get_returns_304_without_planning`: the presenter is never called on a 304.
- `tests/test_api.py::test_etag_changes_when_prices_are_reloaded`.
- `tests/test_api.py::test_gzip_and_post_is_not_cacheable`.
- `tests/test_station_index.py::test_corridor_is_memoized_per_route_and_dropped_on_new_version`.
- `tests/test_station_index.py::test_dataset_version_read_is_cached_for_its_ttl`.
- Locust `ConditionalUser` validates the `304` status and the ETag under load.

## Considered alternatives

- **Memoize the corridor in the use case** rather than the proxy. Rejected: the use case does not know the dataset version, and invalidation belongs with the index that owns that version.
- **Strong ETags.** Rejected: the gzip and identity encodings differ byte-wise, and weak validators are the correct semantics for "same plan".
- **Django's `ConditionalGetMiddleware`.** Rejected: it computes the ETag *after* the response is built, which saves bandwidth but not work.
- **Vectorizing the DP with numpy** (the next candidate). Deferred: it saves about 10 to 15 ms at the cost of a heavy dependency. Revisit if the compute path becomes the bottleneck at the target load.
