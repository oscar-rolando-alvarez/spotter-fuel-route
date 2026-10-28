# Architecture: Spotter Fuel Route API

This document is the map. The **why** behind each decision lives in the [ADRs](adr/0001-record-architecture-decisions.md).

## 1. Quality goals

| # | Quality attribute | Target | How it is met | Evidence |
|---|---|---|---|---|
| Q1 | **Performance** | < 100 ms local compute; total dominated by a single routing call | Offline geocoding, in-memory grid index, O(n·U) DP, plan and route caches, display geometry precomputed once per route | `meta.timings_ms`: corridor 20–60 ms, optimize 10–22 ms; cache hit + present 0.31 ms. [Load test](load-test-report.md), per 8-worker node: ~900 RPS at p95 160 ms mixed; 2,087 RPS warm; 6,289 RPS for 304 revalidations |
| Q2 | **Frugal external usage** | 1 routing call per trip (≤ 3 worst case) | Gazetteer resolver chain; route cache | `meta.external_api_calls`; API tests assert 1, then 0 |
| Q3 | **Correctness** | Never run dry; optimal for the stated objective | Exact DP; greedy oracle; feasibility replay | 47 optimizer tests incl. 25 random routes |
| Q4 | **Modifiability** | Swap router, index or storage without touching the core | Hexagonal ports + composition root | `test_architecture.py`; use case runs on fakes |
| Q5 | **Data freshness** | No stale prices after a reload, across processes | Dataset version namespacing + version-aware index proxy | `test_reloading_prices_invalidates_cached_plans` |
| Q6 | **Operability** | Clear errors and observability | One error model; per-request timings and call counts | 400/422/502 tests; `meta` |
| Q7 | **Scalability and resilience** | Correct under spikes; no stampede on upstream | Stateless workers, single-flight caches, corridor memo, HTTP conditional GET, edge load shedding (ADR-0012, ADR-0013) | 0 wrong answers in ~1.7M validated requests; 2,000-user spike at 953 RPS with 0 errors |

## 2. C4 level 1: system context

```mermaid
flowchart LR
    user["👤 Dispatcher / API client<br/>(Postman, front-end)"]
    sys["🟦 Spotter Fuel Route API<br/>Plans route, cheapest fuel stops<br/>and total fuel cost"]
    osrm["⬜ OSRM<br/>Road routing (external)"]
    nomi["⬜ Nominatim<br/>Free-text geocoding (external, optional)"]
    opis["⬜ OPIS price file (CSV)<br/>Delivered periodically"]
    census["⬜ US Census Gazetteer<br/>Public-domain place centroids"]

    user -- "HTTPS / JSON" --> sys
    sys -- "1 call per trip" --> osrm
    sys -. "only for free-text addresses" .-> nomi
    opis -- "batch load" --> sys
    census -- "build-time data" --> sys
```

## 3. C4 level 2: containers

```mermaid
flowchart TB
    client["API client"]
    subgraph runtime["Spotter Fuel Route (deployable)"]
        api["Django + DRF web app<br/>(stateless workers)"]
        loader["load_fuel_data<br/>management command (batch)"]
        db[("SQLite (baked into the image) → Postgres/PostGIS<br/>Place · FuelStation · FuelDataset")]
        cache[("Redis (docker-compose)<br/>LocMem without REDIS_URL")]
    end
    osrm["OSRM"]
    client --> api
    api -- "version, gazetteer, station details" --> db
    api -- "routes, geocodes, plans" --> cache
    api -- "route" --> osrm
    loader -- "atomic replace + version bump" --> db
```

## 4. C4 level 3: components and the dependency rule

```mermaid
flowchart LR
    subgraph API["api/ (driving adapters)"]
        views["views.py<br/>thin HTTP adapters"]
        ser["serializers.py<br/>input DTO → Command"]
        pres["presenters.py<br/>TripPlan → JSON"]
        err["errors.py<br/>single error model"]
    end
    subgraph APP["application/"]
        svc["PlanTripService<br/>(use case)"]
        csvc["CachedPlanTripService<br/>(Decorator)"]
        meter["metering<br/>(external-call counter)"]
    end
    subgraph DOM["domain/ (pure Python)"]
        model["model.py<br/>value objects / aggregate"]
        ports["ports.py<br/>Protocols"]
        opt["optimizer.py<br/>DP + Greedy (Strategy)"]
        geo["geo.py<br/>haversine · resample · RDP"]
        derr["errors.py"]
    end
    subgraph INF["infrastructure/ (driven adapters)"]
        chain["GeocoderChain<br/>(Chain of Responsibility)"]
        osrmA["OsrmRoutingProvider"]
        cdec["Cached* (Decorators)"]
        idx["LazyStationIndex (Proxy)<br/>→ GridStationIndex"]
        repo["DjangoStationRepository<br/>(Repository)"]
        http["JsonHttpClient<br/>retries · error translation"]
    end
    root["container.py<br/>(Composition Root)"]

    views --> ser & pres & err
    views --> root
    root --> csvc --> svc
    svc --> ports & model & opt
    chain & osrmA & cdec & idx & repo -. "implement" .-> ports
    osrmA & chain --> http --> meter
    root --> chain & osrmA & cdec & idx & repo
```

Arrows point in the direction of dependencies. **Nothing points outward from `domain/`, and `application/` depends only on `domain/`.** `tests/test_architecture.py` enforces this.

## 5. Runtime view: one cold request

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant V as RoutePlanView
    participant S as Serializer
    participant CP as CachedPlanTripService
    participant P as PlanTripService
    participant G as GeocoderChain
    participant R as CachedRoutingProvider→OSRM
    participant I as LazyStationIndex→Grid
    participant O as DP Strategy
    participant DB as Repository (DB)

    C->>V: GET /api/v1/route-plan/?start=Chicago, IL&finish=Denver, CO
    V->>S: validate → PlanTripCommand
    V-->>V: ETag of version, command, settings, host. If-None-Match matches: 304, stop here
    V->>CP: execute(cmd)
    CP->>DB: dataset_version()
    CP-->>CP: cache miss (key = version + command)
    CP->>P: execute(cmd)
    P->>P: make_strategy("dp", $5): fail fast before any I/O
    P->>G: resolve(start), resolve(finish)
    G->>DB: Place lookup ×2 (offline gazetteer)
    P->>R: route(a, b)
    R-->>R: cache miss
    R->>R: OSRM /route (the only external call)
    P->>I: along_route(polyline, 10 mi)
    I->>DB: dataset_version() (rebuild grid if changed)
    I-->>P: 202 CorridorHits (mile marker, offset)
    P->>O: plan(candidates, 1002.7 mi, vehicle, 50 gal)
    O-->>P: FuelPlan (2 purchases)
    P->>P: display geometry (Douglas–Peucker, memoized per route)
    P->>DB: details(ids) (1 query)
    P-->>CP: TripPlan (+timings, calls=1)
    CP-->>V: TripPlan (cached)
    V-->>C: 200 present_trip(plan) + map_url
```

A repeated request stops at step 5 with a cache hit, about 2 ms and 0 external calls.

## 6. Design patterns catalogue

| Pattern (GoF / PoEAA / DDD) | Where | Problem it solves here | Rejected alternative |
|---|---|---|---|
| **Ports and adapters** (Hexagonal) | `domain/ports.py`, `infrastructure/*` | Core independent of OSRM, Django ORM, cache backend | Views calling `requests`/ORM directly |
| **Application service / use case** | `application/plan_trip.py` | One orchestrator; framework-free; testable with fakes | Logic in views |
| **Command** | `PlanTripCommand` | Immutable input; normalized → plan-cache key | Passing `request.query_params` around |
| **Strategy** + **registry/factory** | `domain/optimizer.py` (`DynamicProgrammingStrategy`, `GreedyStrategy`, `STRATEGIES`, `make_strategy`) | Interchangeable objectives; `?strategy=` at runtime | `if algo == ...` branches in the use case |
| **Chain of Responsibility** | `infrastructure/geocoding.py::GeocoderChain` | Cheapest resolver first; network last; add resolvers without edits | Monolithic `resolve()` with nested ifs |
| **Decorator** | `CachedRoutingProvider`, `CachedGeocoder`, `CachedPlanTripService` | Caching as a separate, composable concern with the same interface | Cache logic inside adapters / views |
| **Single-flight** | `application/singleflight.py` (in `CachedRoutingProvider`, `CachedPlanTripService`) | Concurrent misses make one upstream call or computation, so there is no cache stampede | Distributed Redis lock (ADR-0012 upgrade path) |
| **Memoization (bounded LRU)** | `_DisplayGeometry` in `plan_trip.py` | Simplify each route once, not per plan or per response | Simplifying in the presenter (37 ms per response) |
| **Conditional GET (ETag/304)** | `api/http_cache.py` | Revalidations skip all planning work; CDN-friendly | `ConditionalGetMiddleware` (computes after the work) |
| **Virtual Proxy** | `LazyStationIndex` | Defer the expensive index build; rebuild transparently on a new dataset version | Build at import (slow commands); restart on reload |
| **Repository** | `DjangoStationRepository` | Use case sees domain objects, not ORM models | QuerySets leaking into the core |
| **Value Object** / **Aggregate** | `domain/model.py` (frozen, slotted dataclasses; `TripPlan`) | Immutability ⇒ safe caching & concurrency; one consistent result object | Mutable dicts |
| **DTO** (input / output) + **Presenter** | `api/serializers.py`, `api/presenters.py` | Wire format evolves independently of the domain | Serializing domain objects directly |
| **Composition Root** (manual DI) | `container.py` | Single wiring point; tests reset it | Service locator / DI framework |
| **Exception translation** (error boundary) | `api/errors.py` | Domain errors → one HTTP envelope via DRF handler | try/except ladders per view |
| **Architecture fitness function** | `tests/test_architecture.py` | Architecture rules enforced in CI | Wiki-only rules |

## 7. Data model

```mermaid
erDiagram
    FuelDataset ||--o{ FuelStation : "versions (logical)"
    Place {
        string state "USPS code"
        string key  "normalized name (unique with state)"
        string name
        float lat
        float lng
    }
    FuelStation {
        int opis_id "unique, stable"
        string name
        string address
        string city
        string state
        int rack_id
        decimal price "USD/gal, 4 dp"
        float lat "city centroid (ADR-0004)"
        float lng
    }
    FuelDataset {
        int id "singleton = 1"
        string version "sha256(csv)"
        datetime loaded_at
        int stations
    }
```

## 8. Risks and technical debt register

| Item | Impact | Mitigation now | Planned fix |
|---|---|---|---|
| OSRM demo server has no SLA | Latency spikes and outages show up as 502s | Retries, 502 mapping, route cache | Self-host OSRM / ORS HGV (ADR-0003, ADR-0011) |
| Car profile, not truck | Routes may ignore truck restrictions | Documented | ORS HGV profile adapter |
| City-centroid station coordinates | Offset up to ~5 mi | 10-mi corridor; address in response | OPIS coordinates or commercial geocoder (ADR-0004) |
| Sparse West Coast data in the CSV | LA→Seattle is infeasible (422) | Clear 422 with the gap in miles | Data issue: a fuller price feed |
| Per-process LocMem cache | Lower hit rate with N workers | Version namespacing is already multi-worker safe | Redis (settings only) |
| No hours-of-service model | Plans ignore driver breaks | Documented | Extend the DP state or use MILP (ADR-0006) |
| Head-of-line blocking at saturation | `/health` and 4xx queue behind compute (~800 ms at 500 users) | Capacity knee documented (~490 RPS per node) | Edge load shedding, probe isolation, autoscaling (ADR-0012) |
| Cross-worker stampede | Up to 1 OSRM call per worker on a cold burst | Per-process single-flight | Redis lock once Redis is in place |
| Price-reload freshness window | Up to 1 s per worker (version TTL); up to 300 s at intermediaries (`max-age`) | Both configurable; ETag changes with the version | Lower `max-age` or purge the CDN on reload |
