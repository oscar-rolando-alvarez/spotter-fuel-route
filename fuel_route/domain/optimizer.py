"""Cheapest refuelling plan along a fixed route.

Stations sit at known mile markers on the route, fuel can be bought in any amount up
to tank capacity, and price is linear: the classic fixed-path "gas station problem".

Two solvers live here:

* ``greedy_plan``: the textbook optimal greedy for pure cost. At each station, look one
  full tank ahead. If a cheaper station is reachable, buy just enough to reach the
  first one. Otherwise this is the cheapest fuel in range, so fill up (or buy just
  enough to finish) and move to the cheapest station in range. Kept as a reference
  that the tests cross-check the DP against.

* ``plan_fuel_stops``: the production solver, an exact DP over (station, fuel level).
  It optimises the same objective plus an optional per-stop penalty. Pure cost
  minimisation will happily stop to buy 1.2 gallons to save $0.03; the penalty
  prices a stop's time, so a stop is only made when it pays for itself.
  ``stop_penalty=0`` reproduces the greedy optimum.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .errors import NoFeasiblePlanError, UnknownStrategyError
from .model import Candidate, FuelPlan, Purchase, Vehicle

_EPS = 1e-9


def _plan(purchases: list[Purchase], total_miles: float, mpg: float) -> FuelPlan:
    return FuelPlan(
        purchases,
        sum(p.cost for p in purchases),
        sum(p.gallons for p in purchases),
        total_miles / mpg,
    )


def plan_fuel_stops(
    candidates: Sequence[Candidate],
    total_miles: float,
    *,
    range_miles: float,
    mpg: float,
    start_fuel_gallons: float,
    stop_penalty: float = 0.0,
) -> FuelPlan:
    """Minimise ``fuel cost + stop_penalty * stops``. Exact at 1-mile fuel resolution.

    Fuel is tracked in "miles of range" units (0..range). Station markers are rounded
    to whole miles once, not per hop, so rounding error never accumulates.

    Leaving station i with level g costs the minimum of:
      * arriving with g and not stopping: ``arrive[g]``
      * stopping and topping up from some f < g:
        ``penalty + min_{f<g}(arrive[f] - f*unit) + g*unit``
    The inner min is a running prefix minimum, so each station costs O(range) and the
    whole plan O(stations * range), about 0.2M steps for a coast-to-coast trip.
    """
    cap = int(range_miles)
    dest = round(total_miles)
    start = int(min(start_fuel_gallons * mpg, cap))
    if start >= dest:
        return _plan([], total_miles, mpg)
    stations = sorted((c for c in candidates if 0 <= c.mile <= total_miles), key=lambda c: (c.mile, c.price))

    inf = float("inf")
    depart = [inf] * (cap + 1)
    depart[start] = 0.0
    pos = 0
    markers: list[int] = []
    choices: list[list[int]] = []  # choices[i][g] = level we topped up from, or -1 if no stop
    for st in stations:
        m = round(st.mile)
        d = m - pos
        arrive = depart[d:] + [inf] * d
        if min(arrive) == inf:
            raise NoFeasiblePlanError(float(pos), float(d))
        unit = st.price / mpg
        out = arrive[:]
        topped_from = [-1] * (cap + 1)
        best, best_f = inf, -1
        for g in range(1, cap + 1):
            prev = arrive[g - 1] - (g - 1) * unit
            if prev < best:
                best, best_f = prev, g - 1
            cost = stop_penalty + best + g * unit
            if cost < out[g] - _EPS:
                out[g] = cost
                topped_from[g] = best_f
        markers.append(m)
        choices.append(topped_from)
        depart, pos = out, m

    need = dest - pos
    if need > cap or min(depart[need:]) == inf:
        raise NoFeasiblePlanError(float(pos), float(need))
    level = min(range(need, cap + 1), key=lambda g: (depart[g], g))

    # Walk back: departure level at i -> arrival level at i -> departure level at i-1.
    purchases: list[Purchase] = []
    for i in range(len(stations) - 1, -1, -1):
        f = choices[i][level]
        if f >= 0:
            gallons = (level - f) / mpg
            purchases.append(Purchase(stations[i], gallons, gallons * stations[i].price, f / mpg))
            level = f
        level += markers[i] - (markers[i - 1] if i else 0)
    purchases.reverse()
    return _plan(purchases, total_miles, mpg)


def greedy_plan(
    candidates: Sequence[Candidate],
    total_miles: float,
    *,
    range_miles: float,
    mpg: float,
    start_fuel_gallons: float,
) -> FuelPlan:
    """Reference solver: continuous fuel, pure cost, O(n * k) for k stations per tank."""
    capacity = range_miles / mpg
    stations = sorted((c for c in candidates if 0 <= c.mile <= total_miles), key=lambda c: (c.mile, c.price))

    fuel = min(start_fuel_gallons, capacity)
    if fuel * mpg + _EPS >= total_miles:
        return _plan([], total_miles, mpg)
    if not stations or stations[0].mile > fuel * mpg + _EPS:
        raise NoFeasiblePlanError(0.0, stations[0].mile if stations else total_miles)

    purchases: list[Purchase] = []
    pos, i, n = 0.0, 0, len(stations)
    while True:
        here = stations[i]
        fuel -= (here.mile - pos) / mpg
        pos, arrival = here.mile, fuel
        reach = pos + range_miles

        cheaper = cheapest = None
        for j in range(i + 1, n):
            if stations[j].mile > reach + _EPS:
                break
            if stations[j].price < here.price:
                cheaper = j
                break
            if cheapest is None or stations[j].price < stations[cheapest].price:
                cheapest = j

        if cheaper is not None:
            target, nxt = stations[cheaper].mile, cheaper
        elif total_miles <= reach + _EPS:
            target, nxt = total_miles, None
        elif cheapest is not None:
            target, nxt = reach, cheapest
        else:
            raise NoFeasiblePlanError(pos, (stations[i + 1].mile if i + 1 < n else total_miles) - pos)

        buy = max(0.0, min((target - pos) / mpg, capacity) - fuel)
        if buy > _EPS:
            purchases.append(Purchase(here, buy, buy * here.price, arrival))
            fuel += buy
        if nxt is None:
            return _plan(purchases, total_miles, mpg)
        i = nxt


# --- Strategy pattern -------------------------------------------------------------


@dataclass(frozen=True)
class DynamicProgrammingStrategy:
    """Production default: cost + per-stop penalty, exact at 1-mile resolution."""

    stop_penalty: float = 0.0
    name: str = "dp"

    def plan(
        self, candidates: Sequence[Candidate], total_miles: float, vehicle: Vehicle, start_fuel_gallons: float
    ) -> FuelPlan:
        return plan_fuel_stops(
            candidates,
            total_miles,
            range_miles=vehicle.range_miles,
            mpg=vehicle.mpg,
            start_fuel_gallons=start_fuel_gallons,
            stop_penalty=self.stop_penalty,
        )


@dataclass(frozen=True)
class GreedyStrategy:
    """Pure cheapest fuel (ignores stop count). Kept selectable for comparison/demo."""

    name: str = "greedy"

    def plan(
        self, candidates: Sequence[Candidate], total_miles: float, vehicle: Vehicle, start_fuel_gallons: float
    ) -> FuelPlan:
        return greedy_plan(
            candidates,
            total_miles,
            range_miles=vehicle.range_miles,
            mpg=vehicle.mpg,
            start_fuel_gallons=start_fuel_gallons,
        )


# Registry + factory: maps the public ``strategy`` request value to a constructor.
STRATEGIES: dict[str, Callable[[float], DynamicProgrammingStrategy | GreedyStrategy]] = {
    "dp": lambda stop_penalty: DynamicProgrammingStrategy(stop_penalty=stop_penalty),
    "greedy": lambda _stop_penalty: GreedyStrategy(),
}


def make_strategy(name: str, stop_penalty: float) -> DynamicProgrammingStrategy | GreedyStrategy:
    try:
        return STRATEGIES[name](stop_penalty)
    except KeyError:
        raise UnknownStrategyError(f"Unknown strategy {name!r}; choose one of {sorted(STRATEGIES)}") from None
