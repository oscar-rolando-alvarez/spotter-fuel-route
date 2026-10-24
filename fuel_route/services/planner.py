"""Orchestrates one trip plan: geocode -> route (1 external call) -> corridor -> optimise."""

import time
from dataclasses import dataclass

from django.conf import settings

from fuel_route.models import FuelStation

from . import geocoding, routing
from .geo import simplify
from .http import external_calls
from .optimizer import Candidate, plan_fuel_stops
from .station_index import get_station_index

# ~100 m; keeps the returned polyline to a few thousand points for a coast-to-coast trip.
GEOMETRY_TOLERANCE_DEG = 0.001


@dataclass(frozen=True)
class TripRequest:
    start: str
    finish: str
    start_fuel_gallons: float | None = None  # None = full tank
    stop_penalty: float | None = None  # None = settings default


def plan_trip(req: TripRequest) -> dict:
    t0 = time.perf_counter()
    token = external_calls.set(0)
    try:
        cfg = settings.FUEL_ROUTE
        range_miles, mpg = cfg["VEHICLE_RANGE_MILES"], cfg["VEHICLE_MPG"]
        tank = range_miles / mpg
        start_fuel = tank if req.start_fuel_gallons is None else min(req.start_fuel_gallons, tank)
        stop_penalty = cfg["STOP_PENALTY_USD"] if req.stop_penalty is None else req.stop_penalty

        timer = _Timer()
        start = geocoding.resolve(req.start)
        finish = geocoding.resolve(req.finish)
        timer.lap("geocode")
        route = routing.fetch_route(start.point, finish.point)
        timer.lap("routing")

        hits = get_station_index().along_route(route.coordinates, cfg["CORRIDOR_MILES"])
        timer.lap("corridor")
        offsets = {h.station.id: h.offset_miles for h in hits}
        plan = plan_fuel_stops(
            [Candidate(h.station.id, h.route_mile, h.station.price) for h in hits],
            route.distance_miles,
            range_miles=range_miles,
            mpg=mpg,
            start_fuel_gallons=start_fuel,
            stop_penalty=stop_penalty,
        )
        timer.lap("optimize")

        stations = FuelStation.objects.in_bulk([p.candidate.key for p in plan.purchases])
        stops = [
            {
                "sequence": n,
                "route_mile": round(p.candidate.mile, 1),
                "distance_from_route_miles": round(offsets[p.candidate.key], 1),
                "price_per_gallon": round(p.candidate.price, 3),
                "gallons": round(p.gallons, 2),
                "cost": round(p.cost, 2),
                "fuel_on_arrival_gallons": round(p.fuel_on_arrival, 2),
                "station": _station_json(stations[p.candidate.key]),
            }
            for n, p in enumerate(plan.purchases, start=1)
        ]

        line = [[lng, lat] for lat, lng in simplify(route.coordinates, GEOMETRY_TOLERANCE_DEG)]
        return {
            "start": _location_json(start),
            "finish": _location_json(finish),
            "vehicle": {
                "range_miles": range_miles,
                "mpg": mpg,
                "tank_gallons": tank,
                "start_fuel_gallons": round(start_fuel, 2),
            },
            "optimizer": {"algorithm": "dp", "stop_penalty_usd": stop_penalty},
            "summary": {
                "distance_miles": round(route.distance_miles, 1),
                "duration_hours": round(route.duration_hours, 2),
                "total_fuel_cost": round(plan.total_cost, 2),
                "gallons_purchased": round(plan.gallons_purchased, 2),
                "gallons_consumed": round(plan.gallons_consumed, 2),
                "fuel_stops": len(stops),
                "stations_in_corridor": len(hits),
            },
            "fuel_stops": stops,
            "route": {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": line}},
            "meta": {
                "external_api_calls": external_calls.get(),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000),
                "timings_ms": timer.laps,
                "corridor_miles": cfg["CORRIDOR_MILES"],
            },
        }
    finally:
        external_calls.reset(token)


class _Timer:
    def __init__(self):
        self.laps: dict[str, float] = {}
        self._last = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.laps[name] = round((now - self._last) * 1000, 1)
        self._last = now


def _location_json(loc: geocoding.Location) -> dict:
    return {"query": loc.query, "label": loc.label, "lat": loc.lat, "lng": loc.lng, "source": loc.source}


def _station_json(s: FuelStation) -> dict:
    return {
        "opis_id": s.opis_id,
        "name": s.name,
        "address": s.address,
        "city": s.city,
        "state": s.state,
        "lat": s.lat,
        "lng": s.lng,
    }
