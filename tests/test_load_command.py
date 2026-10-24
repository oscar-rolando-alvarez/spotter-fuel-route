import gzip

from django.core.management import call_command

from fuel_route.models import FuelStation, Place

CSV = """OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price
7,WOODSHED OF BIG CABIN,"I-44, EXIT 283 & US-69",Big Cabin,OK,307,3.00733333
9,KWIK TRIP #796,"I-94, EXIT 143",Tomah        ,WI,420,3.28733333
9,KWIK TRIP #796,"I-94, EXIT 143",Tomah,WI,420,3.19900000
11,FLYING J,"I-75",Ruther Glen,VA,1,3.5
12,CANADIAN STOP,"HWY 1",Calgary,AB,1,1.5
13,UNKNOWN PLACE,"",Nowhereville,TX,1,3.0
"""


def test_load_fuel_data(tmp_path, db):
    prices = tmp_path / "prices.csv"
    prices.write_text(CSV)
    places = tmp_path / "places.csv.gz"
    with gzip.open(places, "wt") as f:
        f.write("state,key,name,lat,lng\nOK,bigcabin,Big Cabin,36.54,-95.22\nWI,tomah,Tomah,43.98,-90.50\n")
    overrides = tmp_path / "overrides.csv"
    overrides.write_text("state,key,name,lat,lng\nVA,rutherglen,Ruther Glen,37.93,-77.47\n")

    call_command("load_fuel_data", csv=prices, places=places, overrides=overrides)

    assert Place.objects.count() == 3
    assert set(FuelStation.objects.values_list("opis_id", flat=True)) == {7, 9, 11}
    tomah = FuelStation.objects.get(opis_id=9)
    assert str(tomah.price) == "3.1990"  # lowest of the duplicate rows
    assert tomah.city == "Tomah" and tomah.lat == 43.98

    # Idempotent.
    call_command("load_fuel_data", csv=prices, places=places, overrides=overrides)
    assert FuelStation.objects.count() == 3
