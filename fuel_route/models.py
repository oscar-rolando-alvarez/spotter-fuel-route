from django.db import models


class Place(models.Model):
    """Offline gazetteer entry (US Census places + county subdivisions).

    Lets both stations and "City, ST" user input be geocoded with an indexed
    lookup instead of an external API call.
    """

    state = models.CharField(max_length=2)
    key = models.CharField(max_length=100, help_text="names.place_key() of the name")
    name = models.CharField(max_length=120)
    lat = models.FloatField()
    lng = models.FloatField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["state", "key"], name="uniq_place_state_key")]

    def __str__(self) -> str:
        return f"{self.name}, {self.state}"


class FuelStation(models.Model):
    """One truck stop from the OPIS price file, with coordinates resolved offline."""

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField(null=True)
    price = models.DecimalField(max_digits=7, decimal_places=4, help_text="USD per gallon")
    lat = models.FloatField()
    lng = models.FloatField()

    class Meta:
        indexes = [models.Index(fields=["lat", "lng"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) ${self.price}"


class FuelDataset(models.Model):
    """Singleton row identifying the loaded price file (ADR-0007).

    Web processes compare ``version`` to rebuild their in-memory index and to namespace
    cached plans, so reloading prices in another process (the management command) takes
    effect everywhere without restarts or cache flushes.
    """

    version = models.CharField(max_length=64, help_text="sha256 of the source CSV")
    loaded_at = models.DateTimeField(auto_now=True)
    stations = models.PositiveIntegerField()

    def __str__(self) -> str:
        return f"{self.version[:12]} ({self.stations} stations, {self.loaded_at:%Y-%m-%d %H:%M})"
