# ADR-0011: SQLite and stateless workers for the assessment, with a defined production evolution path

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

Reviewers must be able to run the project in under a minute with `uv sync && migrate && load_fuel_data && runserver`, with no Docker, Postgres or API keys. Production, however, would face concurrent load, a shared cache, a self-hosted router and scheduled price refreshes. The design must make the move from the first to the second a matter of *configuration and adapters*, not a rewrite.

## Decision drivers

- Zero-friction local setup for the assessment.
- Workers must be stateless apart from rebuildable caches, so the service scales horizontally.
- Each production upgrade must be a contained change behind an existing port or setting.

## Decision outcome

### Now (assessment)

- **SQLite** for `Place`, `FuelStation` and `FuelDataset`. The workload is read-mostly and the dataset is about 110k rows. The hot path makes a handful of indexed queries per plan: the dataset version, two gazetteer lookups and one batched station-details query.
- **LocMem cache**, per process.
- **The OSRM public server** (ADR-0003).
- Settings come from environment variables with development defaults, 12-factor style: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `SQLITE_PATH`, `CORRIDOR_MILES`, `STOP_PENALTY_USD`, `CACHE_TTL_SECONDS`, `OSRM_URL`, `NOMINATIM_URL` and `GEOCODER_FALLBACK`.

### Production evolution path

Each step is independent and needs no change in `domain/` or `application/`.

| Concern | Step | Change surface |
|---|---|---|
| DB | Postgres (or Postgres + PostGIS) | `DATABASES` setting. Optionally a PostGIS `CorridorFinder` adapter (ADR-0005) |
| Cache | Redis | `CACHES` setting. Version namespacing already handles multiple workers (ADR-0007) |
| Routing | Self-hosted OSRM (US extract) or OpenRouteService HGV | `OSRM_URL`, or a new adapter plus one line in `container.py` |
| Serving | gunicorn/uvicorn, N workers behind a load balancer; `/api/v1/health/` as readiness probe | Deployment only. The index warms lazily, in about 50 ms per worker |
| Price refresh | A scheduled `load_fuel_data` job (cron, a Kubernetes CronJob or ECS scheduled task) | No code change. Workers pick up the new version automatically |
| Observability | Structured logs plus `meta.timings_ms` exported as metrics (OpenTelemetry) | Middleware and an exporter only |
| Resilience | Circuit breaker around routing, with a stale-route fallback from the cache | A decorator on `RoutingProvider`, the same pattern as caching |
| Security | API keys or OAuth, throttling (DRF `UserRateThrottle`), `DEBUG=0`, a real `SECRET_KEY` | Settings plus DRF config |

### Reference AWS deployment (when needed)

- ECS Fargate or EKS for the stateless API containers.
- RDS Postgres with PostGIS.
- ElastiCache Redis.
- OSRM on EC2, with the US extract built once and stored on EBS or S3.
- EventBridge triggering the loader task, with the OPIS file landed in S3 and read via `--csv`.
- CloudWatch or OpenTelemetry for the timings.

### Consequences

- 👍 A reviewer is running in under a minute, with nothing to install beyond Python and uv.
- 👍 Each production step is reversible and contained, which is the payoff of ADR-0002.
- 👎 SQLite allows one writer at a time, and the loader's transaction briefly blocks other writers. Readers are unaffected under SQLite's default rollback journal for this workload, and Postgres removes the concern entirely.
- 👎 LocMem gives each worker its own cache. Hit rates are lower until Redis is introduced.

## Considered alternatives

- **Postgres and Redis via docker-compose from day one.** 👍 Closer to production. 👎 Adds friction for reviewers (Docker required), and the assessment does not exercise concurrency. A compose file can be added later without code changes.
- **Serverless (Lambda) per request.** 👎 Cold starts would rebuild the grid index and the Django app, losing the in-memory advantages. It is a poor fit for a latency-sensitive, warm-cache design.
