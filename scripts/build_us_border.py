"""Build data/us_border.json.gz from the Census cartographic boundary file (1:5,000,000).

    curl -O https://www2.census.gov/geo/tiger/GENZ2024/kml/cb_2024_us_nation_5m.zip
    unzip cb_2024_us_nation_5m.zip
    uv run python scripts/build_us_border.py cb_2024_us_nation_5m.kml

Output: a list of polygons, each ``[outer_ring, *holes]``, with rings as ``[[lat, lng], ...]``
rounded to 5 decimals (~1 m). Public-domain data; no GIS libraries needed to read it.
"""

import gzip
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "us_border.json.gz"
NS = {"k": "http://www.opengis.net/kml/2.2"}


def ring(el) -> list[list[float]]:
    pts = []
    for token in el.find(".//k:coordinates", NS).text.split():
        lng, lat, *_ = token.split(",")
        pts.append([round(float(lat), 5), round(float(lng), 5)])
    return pts


def main(path: str) -> None:
    polygons = []
    for poly in ET.parse(path).getroot().iterfind(".//k:Polygon", NS):
        outer = ring(poly.find("k:outerBoundaryIs", NS))
        holes = [ring(h) for h in poly.iterfind("k:innerBoundaryIs", NS)]
        polygons.append([outer, *holes])
    OUT.write_bytes(gzip.compress(json.dumps(polygons, separators=(",", ":")).encode()))
    vertices = sum(len(r) for p in polygons for r in p)
    print(f"{len(polygons)} polygons, {vertices} vertices -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
