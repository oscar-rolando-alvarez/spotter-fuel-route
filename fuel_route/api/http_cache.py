"""HTTP conditional requests for route plans (ADR-0013).

A plan is a pure function of (command, loaded price file, vehicle/corridor settings, the
host used to build ``map_url``). Hashing exactly those gives a validator that changes when
— and only when — the response would change, so clients and CDNs can revalidate with
``If-None-Match`` and get a 304 *without the plan being computed or even read from cache*.
"""

import hashlib
import json
from dataclasses import asdict

from django.conf import settings

from fuel_route.application.plan_trip import PlanTripCommand

# Bump when the JSON representation changes, so old ETags stop matching.
REPRESENTATION_VERSION = "1"
CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=60"


def plan_etag(cmd: PlanTripCommand, dataset_version: str, host: str) -> str:
    cfg = settings.FUEL_ROUTE
    material = {
        "repr": REPRESENTATION_VERSION,
        "data": dataset_version,
        "cmd": {k: v.strip().lower() if isinstance(v, str) else v for k, v in asdict(cmd).items()},
        "cfg": [cfg[k] for k in ("VEHICLE_RANGE_MILES", "VEHICLE_MPG", "CORRIDOR_MILES", "STOP_PENALTY_USD")],
        "host": host,
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:32]
    # Weak: the body is semantically identical across gzip/identity encodings.
    return f'W/"{digest}"'


def matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    # Weak comparison (RFC 9110 §8.8.3.2): ignore the W/ prefix on either side.
    tags = {t.strip().removeprefix("W/") for t in if_none_match.split(",")}
    return etag.removeprefix("W/") in tags
