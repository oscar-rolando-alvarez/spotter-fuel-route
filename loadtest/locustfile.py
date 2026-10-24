"""Load scenarios. Every response is validated for correctness, not just status code.

Pick a scenario by user class:
    WarmUser     identical trips   -> plan-cache hits (the common production path)
    ComputeUser  unique commands   -> full pipeline minus routing (corridor + DP every time)
    MixedUser    realistic blend   -> hits, misses, errors (400/422), map HTML, health
    ConditionalUser  revalidation  -> If-None-Match / 304 (what browsers and CDNs do)

Example:
    uv run --group load locust -f loadtest/locustfile.py --headless -u 200 -r 50 -t 60s \\
        --host http://127.0.0.1:8001 WarmUser
"""

import random

from locust import HttpUser, constant, task

from loadtest.trips import TRIPS

OK_TRIPS = [t for t in TRIPS if t[2] == 200]
INFEASIBLE = [t for t in TRIPS if t[2] == 422]
URL = "/api/v1/route-plan/"


def check_plan(resp, expected_cost=None) -> None:
    """Fail the request (Locust marks it red) if the plan is wrong in any way."""
    if resp.status_code != 200:
        resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")
        return
    body = resp.json()
    s, stops = body["summary"], body["fuel_stops"]
    if expected_cost is not None and abs(s["total_fuel_cost"] - expected_cost) > 0.011:
        resp.failure(f"wrong total {s['total_fuel_cost']} != {expected_cost}")
        return
    if abs(sum(x["cost"] for x in stops) - s["total_fuel_cost"]) > 0.05 * max(len(stops), 1):
        resp.failure("stop costs do not add up to total")
        return
    prev, start_range = 0.0, body["vehicle"]["start_fuel_gallons"] * body["vehicle"]["mpg"]
    for i, x in enumerate(stops):
        limit = start_range if i == 0 else body["vehicle"]["range_miles"]
        if x["route_mile"] - prev > limit + 1:
            resp.failure(f"leg of {x['route_mile'] - prev:.0f} mi exceeds range")
            return
        prev = x["route_mile"]
    if body["meta"]["external_api_calls"] > 1:
        resp.failure(f"{body['meta']['external_api_calls']} external calls")
        return
    resp.success()


class WarmUser(HttpUser):
    """Max-throughput, closed loop: repeated trips answered from the plan cache."""

    wait_time = constant(0)

    @task
    def plan(self):
        start, finish, _, cost = random.choice(OK_TRIPS)
        with self.client.get(
            URL, params={"start": start, "finish": finish}, name="route-plan [warm]", catch_response=True
        ) as r:
            check_plan(r, cost)


class ComputeUser(HttpUser):
    """Unique stop_penalty per request busts the plan cache: corridor search + DP every time."""

    wait_time = constant(0)

    @task
    def plan(self):
        start, finish, *_ = random.choice(OK_TRIPS)
        params = {"start": start, "finish": finish, "stop_penalty": f"{random.uniform(0, 20):.6f}"}
        with self.client.get(URL, params=params, name="route-plan [compute]", catch_response=True) as r:
            check_plan(r)


class ConditionalUser(HttpUser):
    """Clients/CDNs that revalidate: after the first 200, send If-None-Match and expect 304."""

    wait_time = constant(0)

    def on_start(self):
        self.etags: dict[tuple[str, str], str] = {}

    @task
    def revalidate(self):
        start, finish, _, cost = random.choice(OK_TRIPS)
        etag = self.etags.get((start, finish))
        headers = {"If-None-Match": etag} if etag else {}
        name = "route-plan [304]" if etag else "route-plan [warm]"
        with self.client.get(
            URL, params={"start": start, "finish": finish}, headers=headers, name=name, catch_response=True
        ) as r:
            if etag:
                if r.status_code == 304 and r.headers.get("ETag") == etag:
                    r.success()
                else:
                    r.failure(f"expected 304, got {r.status_code}")
            else:
                self.etags[(start, finish)] = r.headers.get("ETag", "")
                check_plan(r, cost)


class MixedUser(HttpUser):
    """Production-like blend with small think time."""

    wait_time = constant(0.05)

    @task(70)
    def warm(self):
        WarmUser.plan(self)

    @task(20)
    def compute(self):
        ComputeUser.plan(self)

    @task(3)
    def infeasible(self):
        start, finish, *_ = random.choice(INFEASIBLE)
        with self.client.get(
            URL, params={"start": start, "finish": finish}, name="route-plan [422]", catch_response=True
        ) as r:
            if r.status_code == 422 and r.json()["error"] == "no_feasible_fuel_plan":
                r.success()
            else:
                r.failure(f"expected 422, got {r.status_code}")

    @task(3)
    def invalid(self):
        with self.client.get(URL, params={"start": "Chicago, IL"}, name="route-plan [400]", catch_response=True) as r:
            if r.status_code == 400 and r.json()["error"] == "invalid_request":
                r.success()
            else:
                r.failure(f"expected 400, got {r.status_code}")

    @task(2)
    def map_view(self):
        start, finish, *_ = random.choice(OK_TRIPS)
        with self.client.get(
            URL + "map/", params={"start": start, "finish": finish}, name="route-plan/map", catch_response=True
        ) as r:
            if r.status_code == 200 and "leaflet" in r.text:
                r.success()
            else:
                r.failure(f"map HTTP {r.status_code}")

    @task(2)
    def health(self):
        with self.client.get("/api/v1/health/", name="health", catch_response=True) as r:
            if r.status_code == 200 and r.json()["stations"] > 6000:
                r.success()
            else:
                r.failure(f"health HTTP {r.status_code}")
