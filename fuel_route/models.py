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
