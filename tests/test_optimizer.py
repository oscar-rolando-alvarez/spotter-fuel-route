import math
import random

import pytest

from fuel_route.services.optimizer import Candidate, UnreachableError, greedy_plan, plan_fuel_stops

VEHICLE = {"range_miles": 500, "mpg": 10}


def solve(cands, miles, start=50.0, solver=plan_fuel_stops, **kw):
    return solver(cands, miles, start_fuel_gallons=start, **VEHICLE, **kw)


def assert_feasible(plan, cands_miles, total, start=50.0):
    """Simulate the plan: tank never negative or over capacity, destination reached."""
    fuel, pos = start, 0.0
    for p in plan.purchases:
        fuel -= (p.candidate.mile - pos) / 10
        assert fuel >= -0.11  # 1-mile DP resolution
        fuel += p.gallons
        assert fuel <= 50 + 0.11
        pos = p.candidate.mile
    assert fuel - (total - pos) / 10 >= -0.11


def test_short_trip_needs_no_stop():
    plan = solve([Candidate(1, 100, 3.0)], 400)
    assert plan.purchases == [] and plan.total_cost == 0
    assert plan.gallons_consumed == 40


@pytest.mark.parametrize("solver", [plan_fuel_stops, greedy_plan])
def test_buys_only_what_is_needed_to_finish(solver):
    plan = solve([Candidate(1, 450, 3.0)], 700, solver=solver)
    assert len(plan.purchases) == 1
    p = plan.purchases[0]
    assert math.isclose(p.gallons, 20, abs_tol=0.1)  # 250 mi left, 5 gal on arrival
    assert math.isclose(p.fuel_on_arrival, 5, abs_tol=0.1)
    assert math.isclose(plan.total_cost, 60, abs_tol=0.5)


@pytest.mark.parametrize("solver", [plan_fuel_stops, greedy_plan])
def test_prefers_cheaper_station_ahead(solver):
    # Expensive at 100, cheap at 400: should skip the first and fill at the cheap one.
    cands = [Candidate(1, 100, 4.0), Candidate(2, 400, 2.0)]
    plan = solve(cands, 800, solver=solver)
    assert [p.candidate.key for p in plan.purchases] == [2]
    assert math.isclose(plan.purchases[0].gallons, 30, abs_tol=0.1)


@pytest.mark.parametrize("solver", [plan_fuel_stops, greedy_plan])
def test_fills_up_at_cheapest_when_nothing_cheaper_in_range(solver):
    # Start empty-ish at a cheap station; next one is pricey and the trip needs 2 tanks.
    cands = [Candidate(1, 0, 2.0), Candidate(2, 450, 5.0)]
    plan = solve(cands, 900, start=0, solver=solver)
    first, second = plan.purchases
    assert first.candidate.key == 1 and math.isclose(first.gallons, 50, abs_tol=0.1)
    assert second.candidate.key == 2 and math.isclose(second.gallons, 40, abs_tol=0.1)


@pytest.mark.parametrize("solver", [plan_fuel_stops, greedy_plan])
def test_unreachable_gap_raises(solver):
    with pytest.raises(UnreachableError):
        solve([Candidate(1, 300, 3.0), Candidate(2, 900, 3.0)], 1200, solver=solver)
    with pytest.raises(UnreachableError):
        solve([Candidate(1, 600, 3.0)], 800, solver=solver)  # first station out of reach


def random_route(rng):
    total = rng.uniform(600, 3000)
    n = rng.randint(30, 200)
    cands = [Candidate(i, rng.uniform(0, total), round(rng.uniform(2.7, 4.2), 3)) for i in range(n)]
    # Guarantee feasibility: a station at least every 400 miles.
    cands += [Candidate(1000 + k, m, 3.9) for k, m in enumerate(range(300, int(total), 400))]
    return cands, total


@pytest.mark.parametrize("seed", range(25))
def test_dp_without_penalty_matches_greedy_optimum(seed):
    rng = random.Random(seed)
    cands, total = random_route(rng)
    greedy = solve(cands, total, solver=greedy_plan)
    dp = solve(cands, total, stop_penalty=0)
    assert_feasible(dp, cands, total)
    assert_feasible(greedy, cands, total)
    # Same objective; only the DP's 1-mile fuel resolution separates them.
    tolerance = 0.1 * 4.2 * (len(dp.purchases) + len(greedy.purchases) + 2)
    assert abs(dp.total_cost - greedy.total_cost) <= tolerance


@pytest.mark.parametrize("seed", range(10))
def test_stop_penalty_trades_cents_for_fewer_stops(seed):
    cands, total = random_route(random.Random(seed))
    cheap = solve(cands, total, stop_penalty=0)
    practical = solve(cands, total, stop_penalty=10)
    assert_feasible(practical, cands, total)
    assert len(practical.purchases) <= len(cheap.purchases)
    assert practical.total_cost >= cheap.total_cost - 1e-6
    # The penalised objective is what the DP minimises.
    assert practical.total_cost + 10 * len(practical.purchases) <= cheap.total_cost + 10 * len(cheap.purchases) + 1e-6


def test_dp_is_fast_on_coast_to_coast_sized_input():
    import time

    cands, total = random_route(random.Random(1))
    cands = cands * 3  # ~600 candidates
    t = time.perf_counter()
    solve(cands, total)
    assert time.perf_counter() - t < 0.5
