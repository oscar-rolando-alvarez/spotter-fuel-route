# ADR-0010: Testing strategy: fakes at the ports, oracle and property tests, architecture fitness functions

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

The riskiest code is the optimizer and the corridor projection: subtle off-by-one and rounding bugs that "look right" on a happy-path demo. The second risk is erosion: someone later imports the ORM from the domain "just this once". The suite also has to be fast and hermetic, with no network and no flaky OSRM dependency, so that it runs on every commit.

## Decision drivers

- Prove *correctness*, not only that examples pass.
- Hermetic and fast: no network, and the whole suite in about a second.
- Tests should exercise behaviour through ports, so they survive refactors.
- Architectural rules should be enforced automatically.

## Decision outcome

A layered test portfolio. These are the current counts; `pytest` reports the exact total.

| Layer | Technique | Examples |
|---|---|---|
| **Domain algorithms** | **Oracle testing.** The DP is compared with the independent, provably optimal greedy on 25 seeded random routes | `test_dp_without_penalty_matches_greedy_optimum` |
| | **Property-based invariants.** Plans are replayed: tank never below 0 or above capacity, destination reached, penalty monotonicity | `assert_feasible`, `test_stop_penalty_trades_cents_for_fewer_stops` |
| | **Scenario tests** for each branch of the algorithm | skip expensive, fill at cheapest, unreachable gap |
| | **Performance guard** | 600 candidates in under 0.5 s |
| **Geometry** | Known-answer tests | NYC–LA haversine ≈ 2,446 mi, resampling spacing, Douglas–Peucker corners |
| **Application (use case)** | **In-memory fakes for every port**: no database, HTTP or framework | `test_plan_trip_service.py`: orchestration, metering, fail-fast strategy before I/O, cache decorator and version namespacing |
| **Adapters** | Contract-style tests per adapter. The database is used only where the adapter *is* the database | Geocoder chain ordering, cache decorators, grid index, lazy proxy rebuild, ingestion rules |
| **API (integration)** | Django test client. The HTTP session is mocked at **the lowest level** (`requests.Session.get`) so retries, call counting and error translation are all exercised | shape, 400/422/502, cache hit, price reload |
| **Architecture** | **Fitness functions.** An `ast` import scan enforces the dependency rule (ADR-0002) | `test_architecture.py` |
| **Manual / demo** | Postman collection with assertions | status, call budget, max leg ≤ 500 mi |

### Principles

- **Mock at the boundary you own.** API tests patch the HTTP session, not our own adapters, so the real adapter code runs. Use-case tests use fakes, not mocks, so they assert outcomes and not call sequences.
- **Determinism.** Random tests use fixed seeds, so a failure always reproduces. Caches and the container are reset around every test by an autouse fixture.
- **No network, ever.** The only OSRM and Nominatim traffic comes from manual runs and the Postman collection.

### Consequences

- 👍 The suite catches algorithmic regressions that example-based tests miss. For example, the feasibility replay caught a tank overfill at the DP's 0.1 gal resolution during development.
- 👍 The whole suite runs in about 0.5 s. It is cheap enough to run on save.
- 👍 The architecture cannot silently erode.
- 👎 The oracle depends on the greedy being correct. Mitigated by giving the greedy its own scenario tests and by the independent feasibility replay.
- 👎 There is no live contract test against OSRM. A provider schema change would surface at runtime as a 502, not in CI. Mitigation: add a scheduled, non-blocking smoke test against OSRM in production CI (ADR-0011).

## Considered alternatives

- **Hypothesis** (property-based generation with shrinking). 👍 Better counter-example shrinking. 👎 An extra dependency, and seeded generators already give reproducible coverage. It is the natural next step if the optimizer grows more constraints.
- **VCR cassettes for OSRM.** 👍 Realistic payloads. 👎 Stale fixtures, large files and a false sense of a contract. A minimal synthetic payload documents exactly which fields we rely on.
- **`import-linter`** for layering. 👍 Purpose-built. 👎 An extra tool and config for three rules. The 40-line `ast` test is transparent and has no dependencies.
