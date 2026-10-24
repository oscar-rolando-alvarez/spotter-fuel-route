"""Build data/us_places.csv.gz from the US Census 2024 Gazetteer files.

The output is committed to the repo, so this only needs re-running to refresh it:

    curl -O https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip
    curl -O https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_cousubs_national.zip
    unzip '*.zip'
    uv run python scripts/build_gazetteer.py 2024_Gaz_place_national.txt 2024_Gaz_cousubs_national.txt

Incorporated places / CDPs are written first so they win over county subdivisions
with the same name. Columns: state, key, name, lat, lng.
"""

import csv
import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fuel_route.services.names import census_name_variants, place_key  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "us_places.csv.gz"


def main(paths: list[str]) -> None:
    seen: set[tuple[str, str]] = set()
    with gzip.open(OUT, "wt", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["state", "key", "name", "lat", "lng"])
        for path in paths:
            with open(path, newline="") as f:
                reader = csv.reader(f, delimiter="\t")
                header = [c.strip() for c in next(reader)]
                for row in reader:
                    rec = dict(zip(header, (c.strip() for c in row)))
                    for variant in sorted(census_name_variants(rec["NAME"]), key=len):
                        k = (rec["USPS"], place_key(variant))
                        if k in seen or not k[1]:
                            continue
                        seen.add(k)
                        writer.writerow([k[0], k[1], variant, rec["INTPTLAT"], rec["INTPTLONG"]])
    print(f"wrote {len(seen)} keys to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
