"""Presenter: maps the TripPlan aggregate to the public JSON contract (ADR-0009).

Keeping this separate from the domain lets the wire format evolve (versioning,
rounding, GeoJSON shape) without touching the use case.
"""

from fuel_route.domain.geo import simplify
from fuel_route.domain.model import Location, TripPlan

# ~100 m; keeps the returned polyline to a few thousand points for a coast-to-coast trip.
GEOMETRY_TOLERANCE_DEG = 0.001


def present_trip(plan: TripPlan) -> dict:
    line = [[lng, lat] for lat, lng in simplify(plan.route.coordinates, GEOMETRY_TOLERANCE_DEG)]
    return {
        "start": _location(plan.start),
        "finish": _location(plan.finish),
        "vehicle": {
            "range_miles": plan.vehicle.range_miles,
            "mpg": plan.vehicle.mpg,
            "tank_gallons": plan.vehicle.tank_gallons,
            "start_fuel_gallons": round(plan.start_fuel_gallons, 2),
        },
        "optimizer": {"algorithm": plan.strategy, "stop_penalty_usd": plan.stop_penalty},
        "summary": {
            "distance_miles": round(plan.route.distance_miles, 1),
            "duration_hours": round(plan.route.duration_hours, 2),
            "total_fuel_cost": round(plan.fuel.total_cost, 2),
            "gallons_purchased": round(plan.fuel.gallons_purchased, 2),
            "gallons_consumed": round(plan.fuel.gallons_consumed, 2),
            "fuel_stops": len(plan.stops),
            "stations_in_corridor": plan.stations_in_corridor,
        },
        "fuel_stops": [
            {
                "sequence": s.sequence,
                "route_mile": round(s.purchase.candidate.mile, 1),
                "distance_from_route_miles": round(s.offset_miles, 1),
                "price_per_gallon": round(s.purchase.candidate.price, 3),
                "gallons": round(s.purchase.gallons, 2),
                "cost": round(s.purchase.cost, 2),
                "fuel_on_arrival_gallons": round(s.purchase.fuel_on_arrival, 2),
                "station": {
                    "opis_id": s.station.opis_id,
                    "name": s.station.name,
                    "address": s.station.address,
                    "city": s.station.city,
                    "state": s.station.state,
                    "lat": s.station.lat,
                    "lng": s.station.lng,
                },
            }
            for s in plan.stops
        ],
        "route": {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": line}},
        "meta": {
            "external_api_calls": plan.external_api_calls,
            "elapsed_ms": round(plan.elapsed_ms),
            "timings_ms": plan.timings_ms,
            "corridor_miles": plan.corridor_miles,
            "cache_hit": plan.cache_hit,
        },
    }


def _location(loc: Location) -> dict:
    return {"query": loc.query, "label": loc.label, "lat": loc.lat, "lng": loc.lng, "source": loc.source}
