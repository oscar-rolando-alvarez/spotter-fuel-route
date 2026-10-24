# ADR-0014: Validate "inside the USA" with the Census boundary polygon, not bounding boxes

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez
- **Resolves:** the known gap recorded in ADR-0004 and in the risk register of `docs/architecture.md`

## Context and problem statement

The assignment restricts start and finish to the USA. Coordinate inputs (`"lat,lng"`) and Nominatim results were checked with three coarse bounding boxes covering CONUS, Alaska and Hawaii. The CONUS box reaches 49.5° N, so **southern Canada passed**: Montreal and Vancouver coordinates produced a plan. So did northern Mexico near the border, such as Tijuana and Ciudad Juárez.

## Decision drivers

- Correct at real border towns, where the two sides can be 1 to 2 km apart (Detroit/Windsor, San Diego/Tijuana).
- No GIS dependencies: no GDAL, GEOS, shapely or PostGIS (ADR-0005, ADR-0011).
- Fast enough for a per-request check, well under 1 ms.
- The domain stays pure, and loading the data stays in infrastructure.

## Considered options

1. Tighter, hand-drawn bounding boxes.
2. **The Census cartographic boundary file** (`cb_2024_us_nation_5m`: 1:5,000,000, public domain), with an even-odd point-in-polygon test in pure Python.
3. `shapely` with the same data.
4. Reverse geocoding (Nominatim `/reverse`) to read the country code.

## Decision outcome

**Chosen: option 2.**

- `scripts/build_us_border.py` converts the Census KML into `data/us_border.json.gz`: 295 polygons, 33k vertices, 230 KB, with holes kept.
- `domain/geo.py::Region` holds the polygons with a bounding box per polygon. `contains()` first tests each box, so only one or two polygons are ray-cast, and a point inside a hole (an enclave or a lake) counts as outside. It is pure math, with no I/O.
- `infrastructure/boundary.py::load_region` loads the file once per process (11 ms).
- A new `Boundary` port is injected into `CoordinateGeocoder` and `NominatimGeocoder` by the composition root. In unit tests, a simple box `Region` stands in for it.
- **Measured:** 0.4 ms per check.

### Consequences

- 👍 Correct on every border case tested: Detroit vs Windsor (2 km across the river), Niagara Falls NY vs ON, San Diego vs Tijuana, El Paso vs Juárez, Montreal, Vancouver, the Point Roberts exclave, Key West, Alaska and Hawaii.
- 👍 No new runtime dependencies. The boundary data has a reproducible build script and an official source.
- 👎 At 1:5M resolution a point within a few hundred metres of the border could be misclassified. This is acceptable for city-level trip planning.
- 👎 Great Lakes water counts as outside, because the cartographic boundary excludes water. A coordinate in Lake Michigan is rejected. It is not routable anyway.
- ⚖️ Territories in the file, such as Puerto Rico, count as "USA". They are routable in OSRM, but no fuel stations exist there, so such trips return 422. This is consistent with the data-coverage behaviour in ADR-0009.

### Confirmation

- `tests/test_geo.py::test_us_border` runs 15 parametrized real-world points on both sides of the borders.
- `tests/test_geo.py::test_region_with_hole` covers the polygon-with-hole semantics.
- `tests/test_geocoding.py`: out-of-scope coordinates stop the chain before any network call.

## Pros and cons of the other options

- **Tighter boxes:** cannot follow the 49th parallel *and* the Great Lakes border *and* the Rio Grande. Wrong by construction.
- **shapely:** faster and more robust, but adds a native dependency for one predicate.
- **Reverse geocoding:** an extra external call per coordinate input, which breaks the call budget (ADR-0003).
