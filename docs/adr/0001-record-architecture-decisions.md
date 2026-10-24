# ADR-0001: Record architecture decisions as MADR documents in the repository

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez (architect / backend lead)

## Context and problem statement

This service makes several decisions that are not obvious from the code, and that a reviewer or a future maintainer will question. Examples: why routing is limited to one external call, why stations are geocoded offline, why a DP replaced a provably optimal greedy, and why there is no PostGIS. The code shows *what* was built. It does not show *which alternatives were rejected and why*, or *under which conditions a decision should be revisited*.

## Decision drivers

- Reviewers must understand the trade-offs in minutes, without a meeting.
- Decisions should be revisable: each one needs explicit revisit triggers.
- The documentation must live with the code, be versioned and be reviewed in the same pull request.

## Considered options

1. ADRs in [MADR](https://adr.github.io/madr/) format under `docs/adr/`, one file per decision.
2. One long "design" section in the README.
3. An external wiki (Confluence or Notion).

## Decision outcome

**Chosen: option 1, MADR files in `docs/adr/`.** Each ADR states its context, drivers, the options considered with pros and cons, the decision, its consequences, how it is *confirmed* (the test or metric that keeps it true) and when to revisit it. The README links to the index. `docs/architecture.md` gives the C4 views that tie the ADRs together.

### Consequences

- 👍 Each trade-off is reviewable in isolation and carries its own reasoning.
- 👍 "Confirmation" sections link decisions to executable checks (see ADR-0010). The architecture is therefore enforced, not just described.
- 👎 More documents to keep current. This is mitigated by ADRs being immutable: a changed decision gets a new ADR that supersedes the old one.

## Rules for this repository

- Number ADRs sequentially and never renumber them. Statuses are `Proposed`, `Accepted`, `Deprecated` or `Superseded by ADR-XXXX`.
- A pull request that changes a decision adds a new ADR in the same pull request.
- Keep each ADR short enough to read in five minutes. Details belong in code comments and tests.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-hexagonal-architecture.md) | Hexagonal architecture inside one Django app, enforced by fitness tests | Accepted |
| [0003](0003-routing-provider-osrm-single-call.md) | OSRM as routing provider, one call per trip | Accepted |
| [0004](0004-offline-geocoding-chain.md) | Offline geocoding with a Census gazetteer and a resolver chain | Accepted |
| [0005](0005-in-memory-grid-spatial-index.md) | In-memory uniform-grid spatial index behind a lazy proxy | Accepted |
| [0006](0006-refuelling-optimizer-dp-strategy.md) | Refuelling optimizer: exact DP with a stop penalty, greedy as the reference | Accepted |
| [0007](0007-caching-and-data-freshness.md) | Caching as decorators, invalidated by dataset version | Accepted |
| [0008](0008-price-data-ingestion.md) | Price-file ingestion and cleaning rules | Accepted |
| [0009](0009-api-contract-and-error-model.md) | API contract, presenter and single error model | Accepted |
| [0010](0010-testing-strategy.md) | Testing strategy: fakes at the ports, oracle and property tests, fitness functions | Accepted |
| [0011](0011-persistence-and-deployment-topology.md) | SQLite with stateless workers now, and the evolution path | Accepted |
| [0012](0012-performance-under-load.md) | Performance under load: precomputed display geometry, single-flight, edge load shedding | Accepted |
| [0013](0013-corridor-memo-and-http-caching.md) | Corridor memoization, HTTP conditional GET (ETag/304), configurable gzip | Accepted |
| [0014](0014-us-boundary-polygon.md) | "Inside the USA" via the Census boundary polygon | Accepted |
| [0015](0015-containerization.md) | Containerization: immutable multi-stage image, baked data, Redis-backed compose | Accepted |
