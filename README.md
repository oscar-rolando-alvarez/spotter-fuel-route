# Spotter Fuel Route API

A Django REST API that plans a road trip inside the USA. It returns the driving route, the cheapest set of fuel stops for a truck with **500 miles of range at 10 MPG**, and the **total fuel cost**.

```
GET /api/v1/route-plan/?start=New York, NY&finish=Los Angeles, CA
```

```jsonc
{
  "summary": { "distance_miles": 2810.4, "duration_hours": 50.31, "total_fuel_cost": 705.57,
               "gallons_purchased": 231.0, "fuel_stops": 6, "stations_in_corridor": 460 },
  "fuel_stops": [
    { "sequence": 1, "route_mile": 395.0, "price_per_gallon": 3.059, "gallons": 35.6, "cost": 108.9,
      "station": { "name": "SHEETZ #639", "city": "Youngstown", "state": "OH", "lat": 41.1, "lng": -80.6, ... } },
    ...
  ],
  "route": { "type": "Feature", "geometry": { "type": "LineString", "coordinates": [[-74.0, 40.71], ...] } },
  "map_url": "http://localhost:8000/api/v1/route-plan/map/?start=...",
  "meta": { "external_api_calls": 1, "elapsed_ms": 1392,
            "timings_ms": { "geocode": 4, "routing": 1300, "corridor": 60, "optimize": 20 } }
}
```

`map_url` opens the same plan on a Leaflet map with the route and numbered stops.

## Highlights

- **One external call per trip.** The only network request is the OSRM route. Start and finish geocode offline from a bundled US Census gazetteer. Identical requests come from cache with zero calls.
- **Fast.** About 80 ms of local compute for a coast-to-coast trip; the rest is OSRM's own latency. Cached responses take about 2 ms.
- **Stations geocoded offline, once.** A management command loads the 8,151-row price file into 6,626 unique US stations with coordinates, in about 2 seconds and with no network.
- **Provably good stops.** An exact dynamic program picks the stops. It is cross-checked against the textbook optimal greedy algorithm on randomized routes.
- **Hexagonal architecture, enforced.** The domain and the use case are framework-free behind `typing.Protocol` ports, and a fitness test fails CI if a layer imports the wrong thing. Every significant decision has an ADR: see [Architecture](#architecture-and-decisions).

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). With plain pip, use `pip install -r requirements.txt`.

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py load_fuel_data      # ~2 s, offline
uv run python manage.py runserver
```

```bash
curl "http://localhost:8000/api/v1/route-plan/?start=Chicago,%20IL&finish=Denver,%20CO"
open "http://localhost:8000/api/v1/route-plan/map/?start=Chicago,%20IL&finish=Denver,%20CO"
```

Run the tests and linter:

```bash
uv run pytest            # 92 tests, < 1 s, no network
uv run ruff check .
```

A Postman collection is in [`postman/`](postman/spotter-fuel-route.postman_collection.json).

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` / `POST` | `/api/v1/route-plan/` | Plan a trip (query params or JSON body) |
| `GET` | `/api/v1/route-plan/map/` | The same plan rendered as an HTML map |
| `GET` | `/api/v1/health/` | Station count / index status |

Parameters:

| Name | Required | Description |
|---|---|---|
| `start`, `finish` | yes | `"City, ST"` (also `"City, State"`), `"lat,lng"`, or a free-form US address |
| `start_fuel_gallons` | no | Fuel in the tank at departure, 0–50. Default: full (50 gal = 500 mi) |
| `stop_penalty` | no | USD "cost" of making a stop (default `5`). `0` means cheapest fuel regardless of the number of stops |
| `strategy` | no | `dp` (default: cost plus stop penalty, exact) or `greedy` (pure cheapest fuel, the textbook algorithm) |

Errors use one shape, `{"error": "<code>", "detail": "..."}`:
- `400 invalid_request` (with field details) or `location_not_found` (including locations outside the USA)
- `422 no_feasible_fuel_plan` when a stretch of the route has no station within range. The provided price file barely covers the West Coast (16 stations in CA, 29 in OR), so trips such as LA → Seattle legitimately return this.
- `502 routing_unavailable` when OSRM is down; the HTTP client already retried twice with backoff

## How it works

```
request ─► geocode (offline gazetteer) ─► OSRM route (1 HTTP call, cached)
        ─► corridor search (in-memory grid of stations) ─► DP optimizer ─► JSON / map
```

### 1. Offline data preparation (`manage.py load_fuel_data`)

The price file has city and state but no coordinates. The addresses look like `I-44, EXIT 283 & US-69`, which no free geocoder handles well. Geocoding 6.6k rows at request time, or even at load time through a rate-limited free API (Nominatim allows 1 request per second), would be slow and fragile. Instead:

- **Gazetteer.** `data/us_places.csv.gz` holds about 102k US places with coordinates. It is built from the public-domain **US Census 2024 Gazetteer** files (places and county subdivisions) by `scripts/build_gazetteer.py`. Names are normalized so that `Mc Calla` matches `McCalla`, `Saint Johns` matches `St. Johns`, and `Oklahoma City city` matches `Oklahoma City`. This resolves 97% of station cities.
- **Overrides.** The remaining 138 unincorporated communities (`Ruther Glen, VA`, `Breezewood, PA`, …) were resolved once with `scripts/resolve_unmatched_cities.py` (Nominatim, 1 req/s). Four were filled in by hand. The results are committed in `data/city_overrides.csv`, so loading never touches the network.
- **Cleaning.** Rows for Canadian provinces (620) are skipped because the API is USA only. The file lists many stations several times with different prices, one row per rack. One row per OPIS id is kept, at the lowest price.

Each station is placed at its city centroid. That costs a few miles of precision, which the 10-mile corridor absorbs. It is good enough to choose stops, and the station address is in the response for navigation.

### 2. Routing: one call

The public [OSRM](https://project-osrm.org/) demo server is free, needs no API key and returns the full route geometry in one call: `route/v1/driving/{lng,lat};{lng,lat}?overview=full&geometries=geojson`. Responses are cached for 24 h. Inputs given as `"City, ST"` or `lat,lng` never call a geocoder. Only free-form street addresses fall back to Nominatim, which is cached and can be turned off with `GEOCODER_FALLBACK=0`. The response reports `meta.external_api_calls` so you can verify this.

### 3. Corridor search (`infrastructure/station_index.py`)

Stations are loaded into an in-memory **grid spatial index** (0.25° cells) once per process. The OSRM polyline, often over 20k vertices, is resampled to one point per mile. For each point, only the neighbouring cells are scanned for stations within `CORRIDOR_MILES` (10). Each station keeps its closest approach, which gives its **mile marker along the route** and its offset from the road. This takes about 50 ms for NYC→LA and about 460 candidate stations.

### 4. Choosing the stops (`domain/optimizer.py`)

This is the fixed-path "gas station problem": stations sit at known mile markers, any amount can be bought up to tank capacity (50 gal), and cost is linear in gallons.

**Greedy, the reference.** For pure cost, the classic greedy algorithm is optimal. At each station, look one tank ahead. If a cheaper station is reachable, buy just enough to get to the first one. Otherwise, fill up (or buy just enough to finish) and go to the cheapest station in range. The catch is that the cost-optimal plan is impractical: NYC→LA comes out at **17 stops**, several of them buying 0.1–1.9 gallons to save cents.

**DP, used in production.** It minimizes `fuel cost + stop_penalty × stops` exactly, over the states (station, fuel level), with fuel tracked in 1-mile units (0–500):

```
arrive_i[f]   = depart_{i-1}[f + d(i-1, i)]                      # drive to station i
depart_i[g]   = min( arrive_i[g],                                # don't stop
                     penalty + min_{f<g}(arrive_i[f] + (g-f)·price_i/mpg) )   # stop and top up
```

The inner `min_{f<g}` is a running prefix minimum of `arrive[f] − f·unit`, so each station costs O(range) and a whole trip costs O(stations × 500): about 0.2M steps, or about 20 ms in pure Python. Station mile markers are rounded once, not per hop, so rounding never accumulates.

With the default `$5` penalty, NYC→LA drops from **17 stops to 6** and costs **$705.57 instead of $698.66** (+1%). The fuel bought matches up to rounding, but every stop now buys 27 to 50 gallons. `stop_penalty=0` reproduces the greedy optimum, and the test suite checks this on 25 random routes. `strategy=greedy` returns the pure greedy plan for comparison.

**Assumptions:**
- The truck leaves with a full tank (configurable) and arrives with as little fuel as possible.
- Total cost is the money spent at the pumps on this trip.
- Detours from the highway to a station are ignored. They are at most a few miles because of the corridor width.

## Architecture and decisions

- [`docs/architecture.md`](docs/architecture.md): quality goals, C4 context, container and component views, a sequence diagram, the design-pattern catalogue, the data model and the risk register.
- [`docs/adr/`](docs/adr/0001-record-architecture-decisions.md): 11 Architecture Decision Records in MADR format. Each lists the options considered, the consequences, how the decision is confirmed in tests, and when to revisit it.

| ADR | Decision |
|---|---|
| [0002](docs/adr/0002-hexagonal-architecture.md) | Hexagonal architecture inside one Django app, with the dependency rule enforced by a fitness test |
| [0003](docs/adr/0003-routing-provider-osrm-single-call.md) | OSRM as the routing provider, with exactly one call per trip |
| [0004](docs/adr/0004-offline-geocoding-chain.md) | Offline geocoding with the Census gazetteer, through a Chain-of-Responsibility resolver |
| [0005](docs/adr/0005-in-memory-grid-spatial-index.md) | In-memory grid spatial index behind a lazy, version-aware proxy |
| [0006](docs/adr/0006-refuelling-optimizer-dp-strategy.md) | Exact DP with a stop penalty as the Strategy, with greedy as the reference oracle |
| [0007](docs/adr/0007-caching-and-data-freshness.md) | Caching as Decorators, invalidated by the dataset version |
| [0008](docs/adr/0008-price-data-ingestion.md) | Atomic, idempotent price ingestion with explicit cleaning rules |
| [0009](docs/adr/0009-api-contract-and-error-model.md) | Versioned REST contract, DTOs and presenter, one error model |
| [0010](docs/adr/0010-testing-strategy.md) | Fakes at the ports, oracle and property tests, architecture fitness functions |
| [0011](docs/adr/0011-persistence-and-deployment-topology.md) | SQLite and stateless workers now, and the production evolution path |

Design patterns used, each only where it earns its place:

| Pattern | Where | Why |
|---|---|---|
| Ports and adapters | `domain/ports.py` ↔ `infrastructure/` | Swap the router, index or storage without touching the core |
| Use case + Command | `application/plan_trip.py` | Framework-free orchestration. The command is immutable and doubles as the cache key |
| Strategy + registry | `domain/optimizer.py` | `?strategy=dp\|greedy`. New objectives need no change to the use case |
| Chain of Responsibility | `infrastructure/geocoding.py` | Coordinates → gazetteer → Nominatim, cheapest first |
| Decorator | `infrastructure/caching.py`, `CachedPlanTripService` | Caching as a separate, composable concern |
| Virtual Proxy | `LazyStationIndex` | Lazy index build, with a rebuild when the dataset version changes |
| Repository | `infrastructure/repositories.py` | The use case sees domain objects, never ORM rows |
| DTO + Presenter | `api/serializers.py`, `api/presenters.py` | The wire format evolves independently of the domain |
| Composition root | `container.py` | One wiring point, with no DI framework |

## Project layout

```
config/                         settings (env-driven), urls, DRF exception handler hook
fuel_route/
  domain/                       pure Python: no Django, no I/O (enforced)
    model.py                    value objects + TripPlan aggregate
    ports.py                    Protocols: LocationResolver, RoutingProvider, CorridorFinder,
                                StationRepository, RefuelStrategy, Cache
    optimizer.py                DP + greedy strategies, registry
    geo.py                      haversine, resampling, Douglas–Peucker
    errors.py                   domain errors (each carries its API error code)
  application/
    plan_trip.py                PlanTripService (use case), CachedPlanTripService, PlanTripCommand
    metering.py                 per-request external-call counter
  infrastructure/               driven adapters
    osrm.py · geocoding.py · station_index.py · repositories.py · caching.py · http.py · names.py
  api/                          driving adapters: views, serializers, presenters, errors, urls
  container.py                  composition root
  models.py                     ORM: Place, FuelStation, FuelDataset (version)
  management/commands/load_fuel_data.py
  templates/fuel_route/map.html Leaflet map
data/                           price CSV, gazetteer, overrides (all committed)
scripts/                        reproducible data builders (not used at runtime)
tests/                          pytest; no network (HTTP mocked at requests.Session)
docs/                           architecture.md, adr/, LOOM_SCRIPT.md
postman/                        Postman collection
```

## Configuration

All settings are environment variables with development defaults: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `SQLITE_PATH`, `CORRIDOR_MILES` (10), `STOP_PENALTY_USD` (5), `CACHE_TTL_SECONDS` (86400), `OSRM_URL` (self-host OSRM for production), `NOMINATIM_URL`, `GEOCODER_FALLBACK`.

## Production notes

- **Cache.** Swap LocMemCache for Redis so route and plan caches are shared across workers.
- **OSRM.** The public demo server is rate-limited and has no SLA. Self-host OSRM or use a commercial router. Only `OSRM_URL` changes.
- **Spatial index and prices.** Each worker builds the grid index lazily, in about 50 ms. With PostGIS, the corridor query could become a single `ST_DWithin` against the route line, implemented as another `CorridorFinder` adapter. When the OPIS file is refreshed, rerun `load_fuel_data`. It is idempotent and atomic, and it bumps `FuelDataset.version`, so running workers rebuild their index and stop serving cached plans built from the old prices, with no restart. See [ADR-0011](docs/adr/0011-persistence-and-deployment-topology.md) for the full evolution path.
