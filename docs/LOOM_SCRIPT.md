# Loom demo script (≤ 5 minutes)

## Before you hit record

1. Restart the server so the cache is empty and the first call shows `external_api_calls: 1`:
   `uv run python manage.py runserver`
2. In Postman, import `postman/spotter-fuel-route.postman_collection.json` and check `baseUrl` = `http://localhost:8000`.
3. Open the following in your editor as tabs, in this order: `README.md`, `load_fuel_data.py`, `routing.py`, `station_index.py`, `optimizer.py`, `planner.py`, `tests/test_optimizer.py`.
4. Have a browser tab ready. Close notifications. Use a large font in the editor.
5. Run `uv run pytest` once in a terminal, so you can show the green result quickly.

---

## 0:00 – 0:20 · Intro

> "Hi, I'm Oscar. This is my Django API for the fuel-route assessment. You give it a start and a finish in the USA. It returns the route, the cheapest fuel stops for a truck with 500 miles of range at 10 MPG, and the total fuel cost. Let me show it working, then walk through the code."

## 0:20 – 1:40 · Postman demo

1. **Health.** Send it.
   > "6,626 US stations are loaded and indexed in memory."
2. **NYC → Los Angeles.** Send it, then scroll slowly.
   - `summary`: about 2,810 miles, **$705.57**, 6 stops.
   - `fuel_stops`: route mile, price, gallons and cost for each stop. Point out that no leg exceeds 500 miles (the Tests tab is green).
   - `meta`: **`external_api_calls: 1`**, with `timings_ms` showing that routing takes about 1.3 s and our own work about 80 ms.
   > "Exactly one external call: the OSRM route. Start and finish are geocoded offline."
3. **Send the same request again.**
   > "`cache_hit: true`, zero external calls, a couple of milliseconds."
4. Copy **`map_url`** into the browser.
   > "Here's the map of the route, with the numbered stops and the cost breakdown."
5. **Pure cheapest (stop_penalty=0).**
   > "Strict cheapest is $698.54, but it takes 17 stops, some buying a gallon to save cents. By default I charge a $5 penalty per stop. That gives 6 practical stops for about 1% more. It's a parameter."
6. Quickly show **POST JSON** and **Coordinates + half tank**, then **Error: outside USA** (400).
   > "It accepts JSON or query params, City-and-State or lat/lng, and gives clean errors."

## 1:40 – 4:20 · Code walkthrough

1. **README diagram** (10 s):
   > "The pipeline: geocode offline, one routing call, a corridor search over a spatial index, then an optimizer."
2. **`load_fuel_data.py`** (30 s):
   > "The CSV has no coordinates. I don't geocode 6,000 stations at request time. A management command matches each city against a bundled US Census gazetteer of about 100k places, with name normalization. A one-off script resolved the 3% the gazetteer misses, and that file is committed. Loading is offline and takes 2 seconds. It also dedupes stations listed once per rack, keeping the lowest price, and drops the Canadian rows."
3. **`routing.py`** (15 s):
   > "OSRM's free public server, one call with the full geometry, cached. The HTTP session has retries and counts external calls for the response."
4. **`station_index.py`** (30 s):
   > "Stations go into an in-memory grid of quarter-degree cells. I resample the route to one point per mile and only check the neighbouring cells. Each station within 10 miles gets a mile marker along the route. That's about 50 ms coast to coast."
5. **`optimizer.py`** (60 s), the main part:
   > "This is the fixed-path gas station problem. The greedy here is the textbook optimal one for pure cost: if a cheaper station is within range, buy just enough to reach it; otherwise fill up. It optimizes cents and makes too many stops.
   > So production uses this DP over station and fuel level, in 1-mile units. Leaving a station with g miles of fuel costs either arriving with g, or stopping and topping up from some lower level. That inner minimum is a running prefix minimum, so it's linear per station: about 20 ms for a whole trip. With a zero penalty it reproduces the greedy optimum."
6. **`tests/test_optimizer.py`** (20 s):
   > "Besides unit and API tests with OSRM mocked, there's a property test. On 25 random routes, the DP must match the greedy optimum, and every plan is simulated to make sure the tank never goes negative or over capacity."
   Show `uv run pytest`: **77 passed in under a second.**

## 4:20 – 5:00 · Wrap-up

> "Trade-offs: stations sit at their city centroid, which the 10-mile corridor absorbs. The data has almost no West Coast stations, so a trip like LA to Seattle correctly returns 422. For production I'd swap the local cache for Redis, self-host OSRM, and possibly move the corridor query to PostGIS. Everything is configurable through environment variables. Thanks for watching!"

---

### If something goes wrong live

- **OSRM is slow or down:** the API returns a clean 502. Say it's the public demo server and re-send, since the retry and cache help.
- **You're running over time:** skip `routing.py` and the POST request.
