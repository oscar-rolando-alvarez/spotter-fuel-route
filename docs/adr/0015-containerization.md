# ADR-0015: Containerization: immutable multi-stage image with baked data, Redis-backed compose stack

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez
- **Implements:** the "Serving" and "Cache" steps of the evolution path in ADR-0011

## Context and problem statement

The service must run identically on a laptop, in CI and in a cloud container platform, with one command. ADR-0011 deferred Docker to keep the reviewer setup at "Python plus uv". Containerizing raises its own questions:
- where the price data and gazetteer get loaded;
- how caches behave across workers and replicas;
- how the process is hardened;
- how to load-test the container without abusing public APIs.

## Decision drivers

- Reproducible builds from `uv.lock`, small rebuilds when only code changes, and fast start-up.
- An immutable runtime: no writes and no root.
- Behaviour measured in the container must match the native benchmarks (ADR-0012, ADR-0013).
- `docker compose up` must give a production-shaped stack with a shared cache.

## Decision outcome

### Image (`Dockerfile`, multi-stage)

| Stage | Purpose |
|---|---|
| `deps` | `python:3.14-slim` plus `uv` (pinned image). `uv sync --frozen --no-dev --no-install-project` in its own layer, so code changes don't reinstall dependencies. A BuildKit cache mount keeps rebuilds fast |
| `build` | Copies the code, then runs `migrate` and `load_fuel_data` **at build time**, baking SQLite with 6,626 stations and 102k places. It runs `check --deploy --fail-level ERROR` as a gate |
| `loadtest` | `build` plus the `load` dependency group (Locust). Used only by the compose `loadtest` profile |
| `runtime` (default) | A fresh slim base with only `/app` copied in. **Non-root** (uid 10001), `DJANGO_DEBUG=0`, an HTTP `HEALTHCHECK` on `/api/v1/health/`, and gunicorn as the command. 307 MB |

**Why bake the data.** The price file and gazetteer are versioned in the repository, so an image *is* a dataset version. Start-up needs no migrations or loading, takes seconds, and every replica serves byte-identical data. A price refresh becomes a new image or tag, which is a rollbackable deploy. With Postgres (ADR-0011), the loader would run as a one-off job against the database instead, and `FuelDataset.version` would propagate to running replicas (ADR-0007).

### Process (`gunicorn.conf.py`)

- `gthread` workers, sized with `WEB_CONCURRENCY` (default: CPU count) and `GUNICORN_THREADS` (default 4). These are the settings measured in ADR-0012 and ADR-0013.
- **`post_worker_init` warm-up.** Each worker wires the container, loads the US border and builds the station grid *before* taking traffic. Without it, the first request per worker paid about 20 ms.
- **Worker recycling (`max_requests`) is off by default.** At about 9k RPS a 20k-request limit restarted every worker roughly every 18 s and reset pooled keep-alive connections, causing 0.05% errors (220 of 411k). RSS stayed flat across about 1.7M requests, so the safeguard cost more than it protected. It stays configurable.
- The control socket and worker heartbeat files live on tmpfs (`/tmp`, `/dev/shm`), because the root filesystem is read-only.

### Stack (`docker-compose.yml`)

- **`api`:**
  - `read_only: true`, `tmpfs: /tmp`, `no-new-privileges`;
  - a memory limit (`API_MEMORY_LIMIT`, default 1.5 GB; about 95 MB per worker was measured);
  - waits for Redis to be healthy;
  - all settings come from the environment.
- **`redis`:** `redis:7.4-alpine` as a **pure cache**, with no persistence, `maxmemory 256mb` and `allkeys-lru`. With `REDIS_URL` set, Django uses `RedisCache`, so route, geocode and plan caches are **shared by all workers and replicas**. Correctness is unaffected because the keys are namespaced by dataset version (ADR-0007).
- **`loadtest` profile:** `fake-osrm` serves the recorded routes (mounted read-only) and `locust` runs the scenarios inside the compose network against `http://api:8000`.

### Results in Docker

Docker Desktop VM with 11 vCPUs; api with 8 workers × 4 threads; Redis; Locust in a container on the same VM.

| Scenario | RPS | p95 | Errors | Native (ADR-0013) |
|---|---|---|---|---|
| Warm, 300 users | 1,997 | 260 ms | 0 / 90,012 | 2,087 |
| Compute, 100 users | 243 | 980 ms | 0 / 10,951 | 290 |
| Revalidation 304, 300 users | **8,806** | 58 ms | **0** / 396,667 | 6,289 |
| Mixed, 100 users | 787 | 280 ms | 0 / 35,416 | 907 |
| Spike: 2,000 users at 200/s | 877 | 3.5 s | **0** / 52,689 | 953 |

Container overhead is about 5–15% on the paths dominated by Python and Redis, which is within the VM's expected cost. 304 throughput is *higher* in Docker, because the Linux network stack inside the VM outperforms macOS loopback for many small responses. All 13 baseline trips return the exact expected costs inside the container.

### Consequences

- 👍 `docker compose up --build` gives an immutable, hardened, production-shaped stack in about a minute.
- 👍 Caches are shared across workers and replicas, and the per-process single-flight still prevents in-process stampedes (ADR-0012).
- 👍 The image is suitable for ECS, Kubernetes or Cloud Run as is: stateless, with a health check and a non-root user.
- 👎 A price refresh means rebuilding the image while SQLite is baked in. This is intentional for immutability, and the Postgres path removes it.
- 👎 The image is 307 MB, mostly the Python runtime and the baked database. A distroless base could cut it, at the cost of shell debugging.
- ⚖️ The `--deploy` check reports the expected warnings for an HTTP-only local stack (HSTS, SSL redirect, the default secret key). TLS terminates at the load balancer, and `DJANGO_SECRET_KEY` must be set in real environments.

### Confirmation

- `docker compose up` brings both services to `healthy`.
- A `curl` matrix checked: health, plan, cache hit through Redis, ETag → 304, gzip, Montreal → 400, the read-only filesystem and the non-root user.
- The 13-trip baseline matches inside the container.
- The Locust runs in the table above had 0 errors.

## Considered alternatives

- **Run migrations and the loader at container start (entrypoint).** 👍 One image serves any data. 👎 Every replica rewrites its own SQLite at boot, start-up gets slower, and readiness gets coupled to data loading. Rejected for SQLite, and becomes the right shape with Postgres (as a one-off job).
- **Alpine base.** 👎 musl wheels and slower CPython for CPU-bound work. Slim is the safer default.
- **Persistent Redis** (RDB/AOF). 👎 It is a cache of recomputable values, and persistence adds I/O and recovery semantics for no benefit.
- **nginx sidecar in compose** (compression, load shedding, ADR-0012). Deferred. Add it when deploying beyond a single host, and set `GZIP_RESPONSES=0` then.
