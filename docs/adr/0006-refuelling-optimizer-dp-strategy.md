# ADR-0006: Refuelling optimizer: exact DP with a stop penalty (Strategy), greedy kept as the reference oracle

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

The problem has the following inputs:
- stations at known mile markers along a fixed route, each with a price;
- a tank of *U* = 50 gal, i.e. 500 mi at 10 MPG;
- fuel bought in any quantity, at linear cost;
- a configurable starting fuel level, full by default.

We must choose where to stop and how much to buy so that the truck never runs dry. The assignment says "optimal *mostly* means cost effective".

This is the fixed-path **gas station problem**. For pure cost, a greedy algorithm is provably optimal (Khuller, Malekian & Mestre, *To Fill or Not to Fill*, 2007). On real data, however, the cost-optimal plan is operationally poor. NYC→LA comes out at **17 stops**, several of them buying 0.1 to 1.9 gallons to save a few cents. Every truck stop costs 15 to 20 minutes of a driver's hours-of-service, which is worth far more than the cents saved.

## Decision drivers

- Correctness: the plan must never run dry, and must be provably optimal for its stated objective.
- Practicality: no stop that does not pay for itself.
- Performance: under 50 ms per plan in pure Python.
- Explainability: a reviewer must be able to verify the result.
- Extensibility: other objectives (min stops, preferred brands, HOS windows) must be addable without touching the use case.

## Considered options

1. **Greedy only**, the textbook optimal algorithm for pure cost.
2. **Greedy plus heuristic post-processing**: merge tiny stops.
3. **Exact DP over (station, fuel level)** minimizing `cost + λ·stops`, with λ the per-stop penalty.
4. **MILP** (OR-Tools / CBC) with binary stop variables.
5. **A shortest path** on an expanded state graph with Dijkstra.

## Decision outcome

**Chosen: option 3, the DP, as the default strategy.** The greedy algorithm stays available as a second strategy and serves as the **test oracle**. Both sit behind the `RefuelStrategy` port: **Strategy pattern**, with a small **registry/factory** (`STRATEGIES`, `make_strategy`).

### DP formulation (`domain/optimizer.py::plan_fuel_stops`)

- Fuel is tracked in *miles of range*, 0..500, which is 0.1 gal resolution at 10 MPG. Station mile markers are rounded **once**, not per hop, so rounding error never accumulates along the route.
- `arrive_i[f] = depart_{i-1}[f + d_i]` (drive from the previous station).
- `depart_i[g] = min(arrive_i[g], λ + min_{f<g}(arrive_i[f] + (g − f)·p_i/mpg))` (pass by, or stop and top up).
- The inner minimum is a **running prefix minimum** of `arrive_i[f] − f·unit_i`, so each station costs O(U) instead of O(U²). The whole plan is **O(n·U)**: about 0.2M steps for 460 candidates, or **10 to 22 ms measured**.
- Back-pointers (`topped_from[g]`) reconstruct the purchases in O(n).
- Termination: at the last station, choose the cheapest departure level that reaches the destination. The tie-break is the smaller level, so the truck arrives as empty as possible.
- With λ = 0 the DP solves the same objective as the greedy, up to the 1-mile resolution.

### Defaults and the API

- `strategy=dp` is the default, with `stop_penalty` defaulting to `$5`. The `STOP_PENALTY_USD` setting changes the default and the `stop_penalty` parameter overrides it per request.
- `strategy=greedy` gives the pure cheapest plan, for comparison and for the demo.
- The response echoes `optimizer.algorithm` and `optimizer.stop_penalty_usd`, so every number is reproducible.

### Results on real data (OSRM routes, OPIS prices)

| Trip | Greedy (pure cost) | DP, λ = $5 | Δ cost |
|---|---|---|---|
| NYC → Los Angeles | $698.66, 17 stops | $705.57, 6 stops | +1.0% |
| Buffalo → San Diego | $637.31, 16 stops | $642.89, 6 stops | +0.9% |
| Miami → Seattle | $849.24, 22 stops | $852.59, 8 stops | +0.4% |

### Consequences

- 👍 About a 65% reduction in stops for about 1% more fuel cost, and the trade-off is a single, explicit parameter.
- 👍 Exact for the stated objective, with no heuristics to tune and nothing approximate to hide.
- 👍 New objectives become new strategies. The use case and the API contract do not change, apart from the `strategy` enum.
- 👎 Fuel resolution is 0.1 gal, so totals differ from the continuous greedy by cents. This is tested and bounded.
- 👎 The meaning of λ must be explained to users. It is documented in the README and the ADR, and echoed in the response.

### Confirmation (`tests/test_optimizer.py`)

- **Oracle test.** On 25 seeded random routes (30 to 200 stations, 600 to 3,000 mi), DP with λ = 0 matches the greedy optimum within the resolution bound.
- **Feasibility property.** Every plan is replayed: the tank never goes below 0 or above 50 gal, and the destination is reached.
- **Penalty property.** λ > 0 never yields more stops, never yields a lower cost than λ = 0, and minimizes `cost + λ·stops`.
- Scenario tests: no stop needed, buy only enough to finish, skip an expensive station for a cheaper one ahead, fill up at the cheapest station in range, infeasible gaps.
- Performance guard: 600 candidates must plan in under 0.5 s.
- Strategy registry: the factory builds both strategies and rejects unknown names.

## Pros and cons of the options

**Option 1, greedy only.** 👍 O(n·k), optimal for cost, elegant. 👎 Too many micro-stops, and it cannot express stop costs.

**Option 2, greedy plus merging.** 👍 Simple. 👎 A heuristic with no optimality guarantee, and edge cases where a merge breaks feasibility.

**Option 3, DP with a penalty.** 👍 Exact, fast and tunable. 👎 Discretized at 0.1 gal.

**Option 4, MILP.** 👍 Can express anything (time windows, brand preferences). 👎 Adds a solver dependency, has solver-dependent latency, and is overkill for this objective.

**Option 5, Dijkstra on the state graph.** 👍 Equivalent optimum. 👎 O(n·U·log) with heap overhead, and slower in Python than the prefix-minimum DP for the same answer.

## Revisit when

- **Hours-of-service** rules matter (an 11-hour driving limit, a 30-minute break after 8 hours). Extend the DP state with time, or move to MILP behind the same port.
- Stops must be at preferred brands, or fleet fuel-card discounts apply. Price adjustments go in the `Candidate` construction step, so the algorithm is unchanged.
