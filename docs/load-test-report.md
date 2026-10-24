# Load and stress test report

- **Date:** 2026-10-24
- **Scope:** `GET /api/v1/route-plan/` (warm, compute, cold), `/route-plan/map/`, `/health/`, and the 400/422 error paths.
- **Verdict:** ✅ Every endpoint kept serving correct results under sustained and spike load, across about **1.7M validated requests in two rounds with 0 incorrect responses**. Round 1 (sections 1–5) found and fixed two bottlenecks (ADR-0012). Round 2 (section 0) added corridor memoization, ETag/304 conditional GET and cached dataset-version reads (ADR-0013). Round 3 (section 0b) repeated the tests in Docker with Redis (ADR-0015). Together they **raised per-node capacity at p95 160 ms from about 490 to about 900 RPS**, and the 2,000-user spike now completes with **0 errors**.

## 0. Round 2: current numbers (default configuration, gzip on)

Same harness and host as round 1: gunicorn with 8 workers × 4 threads, fake OSRM at 250 ms, Locust validating every response.

| Scenario | Users (spawn/s) | Requests | Failures | RPS | p50 | p95 | p99 | Round 1 RPS / p95 |
|---|---|---|---|---|---|---|---|---|
| Warm (200s from the plan cache) | 300 (100) | 125,533 | 0 | 2,087 | 110 ms | 230 ms | 300 ms | 2,277 / 270 ms |
| Warm, `GZIP_RESPONSES=0` | 300 (100) | 162,922 | 0 | **2,710** | 110 ms | 170 ms | 210 ms | 2,277 / 270 ms |
| **Revalidation (304)** | 300 (100) | 377,982 | 0 | **6,289** | 33 ms | 55 ms | 82 ms | n/a |
| Compute (corridor + DP every request) | 100 (50) | 17,415 | 0 | **290** | 290 ms | 890 ms | 980 ms | 140 / 1,700 ms |
| Mixed | 25 (25) | 12,129 | 0 | 404 | 4 ms | 36 ms | 55 ms | 328 / 93 ms |
| Mixed | 50 (50) | 19,911 | 0 | 663 | 15 ms | 78 ms | 120 ms | 489 / 160 ms |
| **Mixed** | **100 (100)** | 27,245 | 0 | **907** | 44 ms | **160 ms** | 230 ms | 513 / 480 ms |
| Mixed | 200 (200) | 29,198 | 0 | 972 | 110 ms | 400 ms | 480 ms | 549 / 660 ms |
| **Spike, ramped** | 2,000 (200) | 71,567 | **0** | **953** | 2,100 ms | 2,700 ms | 2,900 ms | 553 / 5,000 ms, 0.04% resets |
| Cold, no cache (TTL 0) | 100 (50) | 8,054 | 0 | 134 | 440 ms | 2,600 ms | 2,800 ms | 95 / 2,700 ms |

**Gzip trade-off.** Compression shrinks NYC→LA from 43.6 KB to 16.5 KB (2.6×) but costs about 23% of warm-path throughput (2,710 → 2,087 RPS) on localhost, where bandwidth is free. Over real networks the smaller payload usually wins. Behind a compressing proxy, set `GZIP_RESPONSES=0`.

**Updated capacity planning.** One 8-worker node sustains about **850 RPS at p95 ≤ 160 ms** with a 20% compute mix (headroom below the ~900 RPS knee), so `nodes = ceil(target_rps / 850)`, plus one for N+1. Repeat traffic that revalidates with ETags is served at about 3× the rate of full 200 responses, with no body.

## 0b. Round 3: the same tests in Docker (ADR-0015)

Setup: `docker compose --profile loadtest` on a Docker Desktop VM with 11 vCPUs. The api runs 8 workers × 4 threads, the cache is **Redis (shared)**, and Locust runs in a container on the same network. All 13 baseline trips return their exact costs in the container.

| Scenario | Requests | Failures | RPS | p95 | Native |
|---|---|---|---|---|---|
| Warm, 300 users | 90,012 | 0 | 1,997 | 260 ms | 2,087 |
| Compute, 100 users | 10,951 | 0 | 243 | 980 ms | 290 |
| Revalidation 304, 300 users | 396,667 | **0** | **8,806** | 58 ms | 6,289 |
| Mixed, 100 users | 35,416 | 0 | 787 | 280 ms | 907 |
| Spike: 2,000 users at 200/s | 52,689 | **0** | 877 | 3.5 s | 953 |

Finding F5, fixed: gunicorn `max_requests = 20000` recycled each worker about every 18 s at 9k RPS and reset pooled keep-alive connections, giving 220 errors (0.05%). Recycling is now off by default, and RSS stayed flat. Memory is about 95 MB per worker (757 MB for 8), and the compose limit was raised to 1.5 GB and made configurable.

# Round 1 (baseline and first fixes)

## 1. Method

| Item | Choice | Why |
|---|---|---|
| Server | gunicorn `gthread`, **8 workers × 4 threads**, `DEBUG=0` | Production-like. Django's dev server is single-process and not representative |
| Routing | **Local fake OSRM** serving 13 *real* recorded OSRM routes, with **250 ms** injected latency | Never stress a free public service. The tests measure *our* service, with realistic upstream latency |
| Load generator | Locust 2.47, closed-loop users, 4–6 processes | Standard, scriptable, gives percentiles |
| Correctness | **Every 200 response is validated.** Warm path: the total cost must equal the baseline to the cent. Compute path: stop costs add up to the total, no leg exceeds the range, ≤1 external call | Catches race conditions in the caches and the lazy index, not just status codes |
| Host | Apple M3 Pro (11 cores, 18 GB), macOS; SQLite; LocMem cache | Load generator and server **share the CPU**, so the numbers are conservative |

Scenarios (`loadtest/locustfile.py`):
- **WarmUser:** identical trips, answered from the plan cache. This is the dominant production path.
- **ComputeUser:** a unique `stop_penalty` per request busts the plan cache, so the corridor search and the DP run every time.
- **MixedUser:** 70% warm, 20% compute, 3% 422, 3% 400, 2% map HTML and 2% health, with 50 ms think time.
- **Cold:** `CACHE_TTL_SECONDS=0`. Nothing is cached, and every request makes the upstream call plus the full computation.

To reproduce, run `uv run python loadtest/record_osrm.py` once, then `loadtest/run_all.sh`.

## 2. Results

| # | Scenario | Users (spawn/s) | Requests | Failures | RPS | p50 | p95 | p99 | Max |
|---|---|---|---|---|---|---|---|---|---|
| 1a | Warm, **before fix** | 300 (100) | 11,833 | 3 (0.03%)¹ | 197 | 1,100 ms | 2,900 ms | 3,100 ms | 3,420 ms |
| 1b | Warm, **after fix** | 300 (100) | 136,791 | **0** | **2,277** | 76 ms | 270 ms | 340 ms | 2,199 ms |
| 2a | Compute, before fix | 100 (50) | 5,419 | 0 | 90 | 1,000 ms | 1,700 ms | 1,800 ms | 2,046 ms |
| 2b | Compute, **after fix** | 100 (50) | 8,414 | **0** | **140** | 570 ms | 1,700 ms | 2,000 ms | 2,727 ms |
| 3 | Mixed, saturated | 500 (100) | 50,458 | **0** | 560 | 810 ms | 1,200 ms | 1,400 ms | 1,974 ms |
| 5a | **Spike** | 2,000 (1,000) | 34,693 | 739 (2.13%)² | 577 | 3,300 ms | 5,200 ms | 5,500 ms | 5,922 ms |
| 5b | Spike, ramped | 2,000 (200) | 41,500 | 16 (0.04%)² | 553 | 3,400 ms | 5,000 ms | 5,600 ms | 6,210 ms |
| 6 | Recovery after the spike | 25 (25) | 4,583 | **0** | 229 | 44 ms | 170 ms | 240 ms | 537 ms |
| 7 | **Cold: no cache**, 250 ms upstream | 100 (50) | 5,701 | **0** | 95 | 680 ms | 2,700 ms | 3,000 ms | 3,508 ms |

¹ The fake OSRM's default listen backlog (5) dropped connections during warm-up. This was a harness defect and is fixed.
² All failures were `HTTP 0` (TCP connection reset), and in 5a all of them fell inside **one second** of the 1,000 users/s ramp. The cause is macOS `kern.ipc.somaxconn = 128`, which caps gunicorn's requested backlog of 4,096. The gunicorn logs show no application errors, and the service recovered immediately (scenario 6).

### Capacity curve (MixedUser, after the fixes)

| Concurrent users | RPS | p50 | p95 | p99 | Failures |
|---|---|---|---|---|---|
| 25 | 328 | 7 ms | 93 ms | 150 ms | 0 |
| **50** | **489** | **34 ms** | **160 ms** | **230 ms** | 0 |
| 100 | 513 | 72 ms | 480 ms | 660 ms | 0 |
| 200 | 549 | 310 ms | 660 ms | 800 ms | 0 |
| 500 | 560 | 810 ms | 1,200 ms | 1,400 ms | 0 |

**The knee is at about 490 RPS with p95 = 160 ms for one 8-worker node.** Beyond it, throughput plateaus at about 560 RPS and latency grows linearly with queueing (Little's law). There are no errors and no collapse, which is the expected behaviour of a CPU-bound, bounded-concurrency server.

### Resources

The total RSS of the gunicorn master and 8 workers was about **860 MB** after the mixed run, roughly 95 MB per worker including the in-memory station index. It stayed flat across runs, with no growth trend. CPU was the limiting resource throughout.

## 3. Findings and fixes

### F1: Geometry simplification ran on every response (fixed: warm 11.5×, compute +55%)

Profiling a single warm request showed 2.8 ms for the cache hit, then **37 ms for Douglas–Peucker simplification of the 35,168-vertex route**, then 0.8 ms of JSON rendering. Simplification lived in the presenter, so it ran on *every* response, cached or not. The cached plan also carried the full-resolution route: **688 KB** pickled per cache get.

**Fix:**
- The use case simplifies once and the `TripPlan` keeps only the display geometry: 1,757 points, a **35 KB** pickle.
- Simplification is **memoized per route** in a small thread-safe LRU, so plans that share a route (different fuel or penalty) don't repeat it.

The cache hit plus presentation went from **40.4 ms to 0.31 ms (130×)**.

### F2: Cache stampede on cold keys (fixed)

When a popular trip misses, N concurrent requests would each call OSRM, breaking the one-call budget, and each recompute the plan.

**Fix:** `SingleFlight` (per-key locks with a re-check after acquiring) in `CachedRoutingProvider` and `CachedPlanTripService`. Concurrent misses for a key wait for one computation. `tests/test_caching.py::test_concurrent_misses_make_a_single_upstream_call` runs 20 threads and expects 1 upstream call. Across processes, the worst case is one call per worker. A shared Redis lock would remove that, and is noted in ADR-0012.

### F3: Head-of-line blocking at saturation (recommendation)

At 500 users even `/health` and the 400 responses waited about 800 ms, because they queue behind compute requests for the same worker threads. This is correct for a saturated node, but bad for orchestrator probes and for SLOs. The recommendations:
- Shed load **at the proxy** (nginx `limit_req`/`limit_conn`, or Envoy adaptive concurrency), returning fast 503s with `Retry-After` instead of queueing.
- Serve liveness probes from the proxy or a separate lightweight worker.
- Autoscale on p95 latency or CPU above about 70%.

### F4: OS accept backlog (environment)

macOS `somaxconn` = 128 caused the resets in the spike. In production, set Linux `net.core.somaxconn` ≥ 4096 and terminate connections at a load balancer, which absorbs connection storms.

## 4. Capacity planning

- One 8-worker node, of about 8 vCPU, sustains about **450 RPS at p95 ≤ 160 ms** with a 20% compute mix. That includes headroom below the 490 knee.
- Nodes are stateless (ADR-0011), so scaling is horizontal: `nodes = ceil(target_rps / 450)`, plus one for N+1.
- With Redis as the shared cache, warm hit rates rise across nodes and per-node capacity moves toward the warm-path ceiling of about 2,000 RPS.
- Cold traffic (unique trips) is bounded by upstream latency and CPU, at about **95 RPS per node with 0 errors**. A self-hosted OSRM, at roughly 5 to 20 ms instead of 250 ms, would roughly double that.

## 5. Caveats

- The load generator ran on the same 11-core machine and competed for CPU, so server-side capacity is understated.
- SQLite and LocMem are the assessment configuration. With Postgres and Redis (ADR-0011), the per-request version query and cache gets move to the network, adding roughly 0.2 to 1 ms per request.
- Fake OSRM latency is constant (250 ms). Real tail latency of the public server is higher and more variable, which is another argument for self-hosting.
