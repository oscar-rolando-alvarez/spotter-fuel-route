"""Repository adapter: the only place the use case's data needs touch the Django ORM."""

import time
from collections.abc import Iterable

from fuel_route.domain.model import StationDetails, StationPoint
from fuel_route.models import FuelDataset, FuelStation


class DjangoStationRepository:
    def __init__(self, version_ttl_seconds: float = 0.0):
        # The version is read on every request (ETag, plan-cache key, index check); a short
        # per-process TTL turns those reads into one query per second per worker (ADR-0013).
        self._version_ttl = version_ttl_seconds
        self._version: tuple[float, str] | None = None

    def all_points(self) -> list[StationPoint]:
        rows = FuelStation.objects.values_list("id", "lat", "lng", "price")
        return [StationPoint(i, lat, lng, float(price)) for i, lat, lng, price in rows]

    def details(self, ids: Iterable[int]) -> dict[int, StationDetails]:
        return {
            s.id: StationDetails(s.id, s.opis_id, s.name, s.address, s.city, s.state, s.lat, s.lng)
            for s in FuelStation.objects.filter(id__in=list(ids))
        }

    def count(self) -> int:
        return FuelStation.objects.count()

    def dataset_version(self) -> str:
        """Identifier of the loaded price file; changes whenever prices are reloaded."""
        now = time.monotonic()
        if self._version is not None and now - self._version[0] < self._version_ttl:
            return self._version[1]
        version = FuelDataset.objects.filter(pk=1).values_list("version", flat=True).first() or "empty"
        self._version = (now, version)
        return version
