# ADR-0008: Price-file ingestion: offline, atomic, idempotent load with explicit cleaning rules

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Oscar Alvarez

## Context and problem statement

`fuel-prices-for-be-assessment.csv` has 8,151 rows with the columns `OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price`. Profiling it showed:

- **620 rows in Canadian provinces** (AB, BC, ON, MB, SK, QC, NS, NB, YT). The API is USA-only.
- **Duplicate station ids.** There are 6,738 unique OPIS ids, and some appear up to 6 times with different prices. These are rack-level rows: the same station is listed once per supply rack.
- **Messy fields**: trailing whitespace in cities (`"Effingham        "`), quoted addresses containing commas, and inconsistent capitalization.
- **No coordinates** (handled in ADR-0004).

## Decision drivers

- Deterministic and reproducible: the same file must always give the same database state and the same dataset version.
- Safe to re-run at any time, so the load must be idempotent.
- Readers must never see a half-loaded dataset, so the load must be atomic.
- The cleaning rules must be explicit and testable, not buried in ad-hoc code.

## Decision outcome

The `manage.py load_fuel_data` management command (`--csv`, `--places`, `--overrides`) does the following:

1. Parses the file with the `csv` module. Never by splitting on commas, because addresses contain quoted commas.
2. Trims every field and upper-cases the state.
3. **Excludes non-US rows** (the state is not one of the 50 states or DC) and reports the count.
4. **Deduplicates by OPIS id, keeping the lowest price.** The rationale is that the pump price a driver pays is the station's posted price, and the multiple rows reflect supply racks, not pumps. Keeping the minimum matches "cheapest available at this stop". The alternative of averaging would invent a price that doesn't exist.
5. Rejects rows with an unparseable id or price instead of guessing.
6. Geocodes from the in-memory gazetteer plus the overrides (ADR-0004), and reports unresolved cities. The current count is 0.
7. Stores prices as `Decimal(7,4)`, with no float rounding in storage. Floats are used only inside the optimizer.
8. **Atomically replaces** `Place`, `FuelStation` and `FuelDataset(version = sha256(file))` in **one transaction**.

The output is 6,626 US stations, all geocoded, plus about 102k gazetteer places, in about 2 s.

### Why "replace" rather than "upsert"

The file is a full snapshot, not a delta. A full replace inside one transaction is simpler and makes deleted stations disappear. It is also exactly as atomic as an upsert. The `FuelDataset.version` bump in the same transaction is what lets running workers notice the change (ADR-0007).

### Consequences

- 👍 Re-running with the same file is a no-op in effect: same rows, same version. Re-running with a new file switches atomically.
- 👍 Each cleaning rule is visible in one place and covered by a test.
- 👎 Station primary keys change on every reload. Nothing outside the process stores them: plans are cached under the dataset version, and responses expose the OPIS id, which is stable.
- 👎 A full reload rewrites about 110k rows. That is fine for a daily batch of this size. Streaming deltas would need a different design (see "Revisit when").

### Confirmation

`tests/test_load_command.py` uses a fixture CSV covering:
- quoted commas;
- trailing whitespace;
- a duplicate id with two prices, where the lowest must win;
- a Canadian row, which must be skipped;
- an unresolvable city, which must be skipped and reported;
- an override-resolved city.

It also asserts the dataset version, and that a second run is idempotent: same rows, same version.

## Considered alternatives

- **Keep every rack row as its own station.** 👎 The optimizer would see phantom duplicates at the same coordinates.
- **Average the duplicate prices.** 👎 It produces a price nobody posts.
- **Pandas-based ETL.** 👎 Adds a heavy dependency for 8k rows. The `csv` module is enough and faster to start.
- **A Celery or Airflow pipeline.** Unnecessary for a daily file. Revisit if ingestion becomes a stream.

## Revisit when

- Prices arrive intra-day per station. Switch to upserts keyed by OPIS id, use per-station versions, and keep an append-only price history table, which also enables trend analytics.
- More countries are supported. Make the country filter configurable and add the matching gazetteers.
