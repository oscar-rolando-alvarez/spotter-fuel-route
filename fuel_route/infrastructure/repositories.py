"""Repository adapter: the only place the use case's data needs touch the Django ORM."""

from collections.abc import Iterable

from fuel_route.domain.model import StationDetails, StationPoint
from fuel_route.models import FuelDataset, FuelStation


class DjangoStationRepository:
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
        return FuelDataset.objects.filter(pk=1).values_list("version", flat=True).first() or "empty"
