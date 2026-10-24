# ADR-0002: Hexagonal architecture (ports and adapters) inside one Django app, enforced by fitness tests

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

The service does four separate things:
1. Resolve places to coordinates.
2. Ask an external router for a route.
3. Find nearby stations with a spatial query.
4. Run an optimization algorithm.

Items 1 to 3 depend on volatile outside systems: a free public API, a CSV that will be replaced, and a database that will likely become PostGIS. Item 4 is the intellectual core and must be testable in isolation, in milliseconds, with property-based tests.

A conventional Django layout of "fat views plus models" would tangle all four. Swapping OSRM for another router, or the grid for PostGIS, would then mean editing the views and the algorithm's call sites. Tests would need the HTTP stack and the database to exercise the algorithm.

## Decision drivers

- **Replaceability** of the router, geocoder, spatial index and storage without touching the use case.
- **Testability**: the core must run with in-memory fakes and no database, network or framework.
- **Proportionality**: this is a small service. The structure must cost less than it saves. That rules out DI frameworks, a mediator or bus, and repository abstractions over every model.
- **Enforceability**: a layering rule that is only written down erodes. It has to fail CI when violated.

## Considered options

1. **Classic Django (MVT plus service functions).** Logic lives in views and service modules that import the ORM and `requests` directly.
2. **Hexagonal / Clean Architecture, lightweight.** Domain, application, infrastructure and API layers in one Django app. Ports are `typing.Protocol`s, wiring is plain constructor injection in a composition root, and the rule is enforced with an import-scanning test.
3. **Hexagonal with a DI container** (`dependency-injector`, `punq`) and separate installable packages per layer.
4. **Microservices**: routing, optimization and API as separate deployables.

## Decision outcome

**Chosen: option 2.**

```
fuel_route/
  domain/          pure Python: model (value objects), errors, ports (Protocols), geo, optimizer
  application/     use case PlanTripService + CachedPlanTripService, PlanTripCommand, metering
  infrastructure/  adapters: OSRM, geocoders, grid index, Django repository, cache decorators, HTTP
  api/             DRF views (thin), serializers (input DTO), presenters (output DTO), error mapping
  container.py     composition root: the only module that knows the concrete classes
  models.py        Django ORM models (Django requires this location)
```

**Dependency rule:** `api → application → domain ← infrastructure`, and only `container.py` sees everything. Specifically:
- The domain imports nothing from Django, DRF, `requests` or any outer layer.
- The application layer imports only the domain. Its cache dependency is the `Cache` port, not `django.core.cache`.
- Infrastructure never imports the API layer or the container.

**Why Protocols and not ABCs.** Structural typing lets the adapters, Django's cache and the test fakes satisfy a port without inheriting from it. The domain stays free of registration code, and fakes stay trivial.

**Why no DI container.** The whole object graph is about 15 lines in `container.py`. A library would add indirection, magic and a dependency without removing any real complexity. The `reset()` hook covers the test-override need that DI containers usually justify.

### Patterns this ADR introduces

These are used only where they pay for themselves:

| Pattern | Where | Why here |
|---|---|---|
| Ports and adapters | `domain/ports.py` ↔ `infrastructure/*` | Swap OSRM, the grid or ORM storage without touching the use case |
| Application service / use case | `application/plan_trip.py` | One place that orchestrates the pipeline. Framework-free |
| Command object | `PlanTripCommand` | Immutable input. Doubles as the plan-cache key material |
| Composition root | `container.py` | Single wiring point. Configuration is read once |
| Value objects | `domain/model.py` (frozen, slotted dataclasses) | Immutability makes caching and concurrency safe by construction |
| Data transfer objects | `api/serializers.py` (in), `api/presenters.py` (out) | The wire format can evolve without touching the domain |

Further patterns are introduced by their own ADRs: Strategy (0006), Chain of Responsibility (0004), Decorator (0007), Virtual Proxy (0005), Repository (0005, 0008) and an error-translation boundary (0009).

### Consequences

- 👍 The optimizer, the corridor search and the use case run in tests with zero I/O. The 47 optimizer tests, including the 25-route oracle suite, run in about 0.3 s.
- 👍 Changing routers is a new adapter plus one line in the composition root. `test_plan_trip_service.py` proves the use case runs against fakes.
- 👍 Each layer can be read on its own. A reviewer can open `domain/optimizer.py` without seeing any HTTP code.
- 👎 More files than a minimal Django app (about 20 modules), and a newcomer must learn the layer map. Mitigated by `docs/architecture.md` and the docstrings at the top of each module.
- 👎 Some mapping code (ORM row → `StationDetails` → JSON). This is accepted; it is exactly what decouples the wire format from storage.
- ⚖️ Django's ORM still lives in `fuel_route/models.py`, because Django requires that location. Only infrastructure and the management command import it.

### Confirmation

`tests/test_architecture.py` parses every module's imports with `ast`, resolving relative imports, and fails if any layer imports a forbidden prefix. It runs in the normal `pytest` suite, so a violation fails CI like any other regression.

## Pros and cons of the options

**Option 1, classic Django.** 👍 Fewest files and familiar to every Django developer. 👎 The algorithm and the I/O get coupled. Tests need the database and HTTP mocks everywhere. Swapping a provider touches the views.

**Option 2, lightweight hexagonal.** 👍 Isolation, testability and replaceability, at low cost. 👎 There is a layer map to learn.

**Option 3, hexagonal with a DI container and multiple packages.** 👍 Strictest boundaries. 👎 Ceremony out of proportion to a single use case. Packaging overhead. The container's magic hides the object graph.

**Option 4, microservices.** 👎 Network hops would erase the latency budget (the target is under 100 ms of local compute). It needs distributed tracing, multiple deployables and contract versioning, all for one use case. Rejected outright.

## Revisit when

- A second, unrelated use case arrives, such as fleet scheduling. Consider splitting it into its own bounded-context app with its own ports.
- The team grows past about 5 engineers on this codebase. Consider moving to separate packages so the dependency rule is checked by the packaging and not only by a test.
