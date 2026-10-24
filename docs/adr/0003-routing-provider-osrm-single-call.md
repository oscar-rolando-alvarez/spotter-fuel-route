# ADR-0003: OSRM as the routing provider, with exactly one routing call per trip

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

The assignment requires a free map/routing API. It states that one call per request is ideal, and that two or three are acceptable. The route geometry is needed for three things: to draw the map, to find stations along the way, and to get the driving distance the fuel computation uses. Distances must be road distances, not straight lines, because a 500-mile range is a road-distance constraint.

## Decision drivers

- Free, with no API key, so reviewers can run the project without signing up.
- Full-resolution geometry and road distance returned in **a single request**.
- US coverage on real road networks.
- Low latency. A provider that can be self-hosted is a strong plus, for production.
- Graceful failure: clear errors, bounded retries, no hanging requests.

## Considered options

1. **OSRM public demo server** (`router.project-osrm.org`).
2. **OpenRouteService.** Free tier, API key required, 2,000 requests per day.
3. **GraphHopper.** Free tier, API key required, rate-limited.
4. **Mapbox or Google Directions.** Excellent, but need a key and billing, and are not "free" in the assignment's sense.
5. **Self-hosted OSRM or Valhalla** from day one.

## Decision outcome

**Chosen: option 1, OSRM, behind the `RoutingProvider` port,** called once per trip as:

```
GET /route/v1/driving/{lng,lat};{lng,lat}?overview=full&geometries=geojson&steps=false&alternatives=false
```

- `overview=full` returns full-resolution geometry, which keeps corridor matching accurate. The presenter later simplifies it for the response with Douglas–Peucker at 0.001°, about 100 m.
- `steps=false` and `alternatives=false` keep the payload minimal. Turn-by-turn directions are not needed.
- The start and finish are geocoded **offline** (ADR-0004), so `"City, ST"` and `"lat,lng"` inputs make **exactly one** external call. Only a free-form street address adds one Nominatim call, which is cached; the worst case is three calls.
- `CachedRoutingProvider` (ADR-0007) makes repeated trips cost zero calls.
- `meta.external_api_calls` reports the count per request, which makes the constraint observable.

### Resilience

- `JsonHttpClient` uses a pooled `requests.Session` with `Retry(total=2, backoff_factor=0.3, status_forcelist=429/502/503/504)` for idempotent GETs only, and a 15 s timeout.
- Every transport or parse failure becomes `ProviderUnavailableError`, which the API maps to `502 routing_unavailable`. A provider outage never shows up as a 500.
- An OSRM answer of `code != "Ok"` (for example `NoRoute`) is also treated as a provider error, with OSRM's own message.

### Consequences

- 👍 Zero setup for reviewers. One HTTP round trip per trip. GeoJSON can be used directly by the map and the corridor search.
- 👍 The same API can be self-hosted (`osrm-backend` with a US extract) by changing the `OSRM_URL` setting only.
- 👎 The demo server has no SLA and is rate-limited. Measured latency varies from 0.2 s to 1.4 s, so it dominates the response time; our own compute is about 50 to 85 ms (see the `meta.timings_ms` breakdown). This is acceptable for an assessment and not for production (ADR-0011).
- 👎 The OSRM car profile is not a truck profile: there are no height, weight or hazmat restrictions. This is documented as a known limitation.

### Confirmation

- `tests/test_api.py::test_plan_returns_route_stops_and_cost` asserts `external_api_calls == 1` and that the HTTP session was called exactly once.
- `test_post_json_and_cache` asserts that the second identical request makes 0 calls.
- `test_upstream_failure_is_502` covers the failure mapping.

## Pros and cons of the options

| Option | Key needed | Calls per trip | Self-hostable | Truck profile | Verdict |
|---|---|---|---|---|---|
| OSRM demo | No | 1 | Yes (same API) | No | ✅ Chosen |
| OpenRouteService | Yes | 1 | Yes | Yes (HGV) | Good. A reviewer would need a key |
| GraphHopper | Yes | 1 | Yes | Yes (paid) | Same as above |
| Mapbox / Google | Yes plus billing | 1 | No | Partial | Not "free" |
| Self-hosted OSRM now | No | 1 | n/a | No | About 30 GB of preprocessing for the US. Excessive for an assessment |

## Revisit when

- Going to production: self-host OSRM, or use OpenRouteService HGV for truck-legal routing. Only the adapter and the composition root change.
- If p95 latency becomes an SLO, add a circuit breaker such as `pybreaker` around the adapter, with a short timeout and a stale-cache fallback.
