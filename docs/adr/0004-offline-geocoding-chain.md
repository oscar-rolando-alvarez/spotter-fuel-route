# ADR-0004: Offline geocoding with a US Census gazetteer and a Chain-of-Responsibility resolver

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

There are two geocoding needs.

1. **Stations (bulk, about 6.6k unique).** The OPIS file has `City`, `State` and an `Address` such as `I-44, EXIT 283 & US-69`, but **no coordinates**. Free geocoders handle interstate-exit addresses poorly. Nominatim's usage policy allows 1 request per second, so geocoding at request time is impossible, and even a bulk load would take about 2 hours.
2. **User input (two per trip).** Calling a geocoder for the start and the finish would use two or three external calls per trip, against the one-call goal (ADR-0003).

## Decision drivers

- Zero network calls on the hot path for the common input forms: `"City, ST"` and `"lat,lng"`.
- A deterministic, reproducible station dataset with an auditable source.
- Coverage above 99% of the US stations in the file.
- Free-form addresses should still work, at the cost of extra calls, without hard-coding that path into the use case.

## Considered options

1. **Geocode stations at request time** with Nominatim or Census.
2. **Bulk geocode the station addresses** once, with the Census Batch Geocoder or Nominatim, and store the coordinates.
3. **City-centroid geocoding** from the public-domain **US Census 2024 Gazetteer** (places plus county subdivisions, about 102k names), with a small committed override file for the rest. **The same gazetteer resolves user `"City, ST"` input offline.**
4. A commercial geocoder (Google or Mapbox).

## Decision outcome

**Chosen: option 3,** behind the `LocationResolver` port, implemented as a **Chain of Responsibility**:

```
GeocoderChain([
    CoordinateGeocoder(),                          # "lat,lng" literal: no I/O
    GazetteerGeocoder(),                           # "City, ST" / "City, State" / "..., USA": 1 indexed SQL lookup
    CachedGeocoder(NominatimGeocoder(...)),        # free-form addresses only; optional (GEOCODER_FALLBACK)
])
```

- Each handler returns a `Location`, or `None` to pass the query on.
- A handler may also raise to **stop** the chain with a definitive answer. `CoordinateGeocoder` does this for coordinates outside the USA, so they are never forwarded to the network.
- The chain raises `LocationNotFoundError` if no handler resolves the query, which becomes `400 location_not_found`.
- Ordering is part of the design: cheapest and most specific first, network last.

### Name normalization

This is shared by the bulk load and runtime lookups, in `infrastructure/names.py`.
- Census legal suffixes are stripped: `Oklahoma City city` becomes `Oklahoma City`, and `Nashville-Davidson metropolitan government (balance)` yields both `Nashville-Davidson` and `Nashville`.
- Keys are canonicalized: lowercase, `Saint`/`St.` → `st`, `Fort`/`Ft.` → `ft`, `Mount`/`Mt.` → `mt`, and spaces and punctuation are removed. As a result `Mc Calla` matches `McCalla` and `De Forest` matches `DeForest`.
- Incorporated places are written before county subdivisions, so the more specific entity wins a name collision.

### Coverage

- The gazetteer resolves 97% of the US station cities.
- The remaining 138 unincorporated communities (`Ruther Glen, VA`, `Breezewood, PA`, …) were resolved **once, offline** by `scripts/resolve_unmatched_cities.py`, which calls Nominatim at ≤1 request per second with an identifying User-Agent. Four were resolved by hand.
- The result is committed in `data/city_overrides.csv`, giving **100% of US stations geocoded with no network at load time.**

### Consequences

- 👍 Typical requests make no geocoding calls, which preserves the one-call budget.
- 👍 Loading is deterministic and offline, and takes about 2 s. The data is public domain with reproducible build scripts (`scripts/build_gazetteer.py`).
- 👍 New resolvers (ZIP codes, a commercial geocoder, a fleet's depot names) are added as chain links with no change to the use case.
- 👎 **Precision.** A station is placed at its city's internal point, not at the pump, so the error is typically 1 to 5 miles. Mitigations: the 10-mile corridor (ADR-0005) absorbs it, the response returns the station's street address for navigation, and the error does not affect *which* station is cheapest, only the reported `distance_from_route_miles`.
- 👎 Two stations in the same city share coordinates. This is harmless to the optimizer, which works on route mile and price.
- ⚖️ The gazetteer adds about 1.4 MB (gzipped) to the repository. This is accepted for reproducibility.

### Confirmation

- `tests/test_geocoding.py` checks chain ordering:
  - a gazetteer hit never reaches the network;
  - out-of-USA coordinates stop the chain;
  - Nominatim results, including misses, are cached;
  - an empty query is rejected.
- `tests/test_names.py` covers the normalization rules.
- `load_fuel_data` reports the number of unresolved cities; the current count is 0.

## Pros and cons of the options

**Option 1, request-time geocoding.** 👎 Breaks the call budget and the latency budget, and violates Nominatim's policy at any real load.

**Option 2, bulk address geocoding.** 👍 Rooftop precision where it works. 👎 Interstate-exit addresses geocode poorly, so a city fallback would be needed anyway. It takes about 2 h at 1 request per second, and the pipeline would not be reproducible offline.

**Option 3, gazetteer plus overrides.** 👍 Offline, deterministic, free and complete. 👎 City-level precision.

**Option 4, commercial geocoder.** 👍 Best precision. 👎 Needs a key and costs money, so a reviewer could not run the project as is.

## Revisit when

- Stop-level precision matters, for example turn-by-turn directions to the pump. Then enrich the stations with real coordinates from OPIS (which has them) or a commercial geocoder, through the same loader.
- The input form needs ZIP codes. Add a `ZipGeocoder` link using the Census ZCTA gazetteer.
- **Known gap:** `in_usa()` uses three coarse bounding boxes, so some southern-Canada coordinates (Montreal, Vancouver) pass the coordinate check. The fix is a point-in-polygon test against the Census cartographic boundary file inside `CoordinateGeocoder`; it is tracked as technical debt in `docs/architecture.md`.
