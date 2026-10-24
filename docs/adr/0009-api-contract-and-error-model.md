# ADR-0009: API contract: versioned REST resource, input and output DTOs, and one error model

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

The API will be exercised from Postman by reviewers, and potentially by a front end that draws the route on a map. It needs:
- a stable, self-describing response;
- errors that a client can branch on;
- a shape that can evolve without breaking clients.

A trip plan is a pure computation with no server-side state change, but its input is a bit too rich for a short query string. It may include coordinates, a strategy and a penalty.

## Decision drivers

- Postman-friendly: a shareable URL for quick demos, and a JSON body for programmatic clients.
- Clients branch on machine-readable error codes, not on message text.
- No business logic in views, which must stay thin adapters.
- Responses should be inspectable: every number explainable, with timings and call counts.

## Decision outcome

### Resource and methods

- `GET /api/v1/route-plan/?start=…&finish=…[&start_fuel_gallons][&stop_penalty][&strategy]` is safe, cacheable and shareable. It also yields the `map_url`.
- `POST /api/v1/route-plan/` takes the same fields as a JSON body, for programmatic clients. It is treated as a query, not a resource creation, so it returns 200 and not 201.
- `GET /api/v1/route-plan/map/` takes the same parameters and returns a Leaflet HTML view, intended for humans and the demo.
- `GET /api/v1/health/` returns the station count and the index status, for readiness probes.
- **URI versioning** (`/api/v1/`). A breaking change ships as `/api/v2/` next to v1. This was chosen over header versioning because reviewers use Postman and curl, where a visible version is clearer.

### Layers inside the API package

- **Input DTO:** `PlanTripRequestSerializer` validates types and ranges (start fuel 0 to 50, penalty 0 to 500, strategy within the registry) and produces an immutable `PlanTripCommand`. The view never touches raw parameters.
- **Use case:** `container.plan_trip.execute(command)` returns the `TripPlan` aggregate.
- **Output DTO / Presenter:** `present_trip(plan)` builds the JSON:
  - rounding: miles to 0.1, money to cents, price to $0.001;
  - GeoJSON `Feature<LineString>` in `[lng, lat]` order, per RFC 7946;
  - simplification with Douglas–Peucker at about 100 m.
  - The domain has no knowledge of JSON.

### Response shape (stable keys)

`start`, `finish`, `vehicle`, `optimizer`, `summary`, `fuel_stops[]`, `route` (GeoJSON), `meta`, and on GET/POST also `map_url`. The `meta` object has `external_api_calls`, `elapsed_ms`, `timings_ms{geocode,routing,corridor,optimize}`, `corridor_miles` and `cache_hit`. It makes the performance requirements *observable per request*.

### One error model

Every failure is `{"error": "<machine_code>", "detail": <string | field errors>}`. The status codes live in **one table** (`api/errors.py::STATUS_BY_ERROR`), and a custom DRF `EXCEPTION_HANDLER` applies it. Views contain no try/except ladders.

| Domain error | HTTP | `error` |
|---|---|---|
| DRF `ValidationError` | 400 | `invalid_request` (`detail` = field errors) |
| `LocationNotFoundError` | 400 | `location_not_found` |
| `UnknownStrategyError` | 400 | `unknown_strategy` |
| `NoFeasiblePlanError` | **422** | `no_feasible_fuel_plan`: the request is valid but no feasible plan exists with the available stations |
| `ProviderUnavailableError` | **502** | `routing_unavailable`: the upstream provider failed. Logged at WARNING |
| anything else | 500 | DRF default. A bug, never an expected path |

**Why 422 and not 404 or 400.** The input is syntactically and semantically valid. The *domain* cannot satisfy it given the data: the CSV has almost no West Coast stations, so LA→Seattle is infeasible. 422 tells clients not to retry with the same input and not to treat it as a server fault.

**Why 502 and not 503 or 500.** The fault is in an upstream dependency, after retries. 502 is the standard gateway semantic and lets monitors tell upstream failures apart from our own bugs.

### Consequences

- 👍 Views are about 10 lines each and contain only parse → execute → present.
- 👍 Clients get one predictable error envelope. The `error` codes are part of the contract and the `detail` text can change freely.
- 👍 The `meta` timings make the "fast" and "few calls" requirements verifiable in the Loom demo and in production logs.
- 👎 GET with a body-like query string is long for coordinate inputs. POST covers that case.
- ⚖️ No pagination or HATEOAS, which are not needed for a single computed resource.

### Confirmation

`tests/test_api.py` covers:
- the response shape;
- POST and GET parity and caching;
- coordinate input;
- validation errors (400, `invalid_request` with field details);
- an unknown location (400);
- an infeasible plan (422);
- an upstream failure (502);
- strategy selection;
- map rendering;
- the health check.

The Postman collection (`postman/`) asserts status codes, the call budget and that no leg exceeds 500 miles.

## Considered alternatives

- **GraphQL.** 👎 A single fixed-shape computation gains nothing, and it complicates caching and Postman demos.
- **RFC 7807 `application/problem+json`.** 👍 It is a standard. 👎 It is heavier than reviewers need. The envelope here maps 1:1 to it (`error` → `type`, `detail` → `detail`), so migrating later is mechanical.
- **Async job resource** (`POST /plans` → 202, then poll). 👎 Unnecessary when p95 is under 2 s. Revisit if HOS-aware or multi-day planning makes computation slow.
