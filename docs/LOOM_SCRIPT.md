# Loom demo script (≤ 5 minutes)

## Before you hit record

1. Restart the server so the cache is empty and the first call shows `external_api_calls: 1`:
   `uv run python manage.py runserver`
2. In Postman, import `postman/spotter-fuel-route.postman_collection.json` and check `baseUrl` = `http://localhost:8000`.
3. Open the following in your editor as tabs, in this order: `docs/architecture.md` (Markdown preview, so the Mermaid diagrams render), `fuel_route/container.py`, `fuel_route/application/plan_trip.py`, `fuel_route/domain/optimizer.py`, `fuel_route/infrastructure/station_index.py`, `docs/adr/` (folder listing), `tests/test_architecture.py`.
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
5. **Pure cheapest (stop_penalty=0)**, or add `strategy=greedy`.
   > "Strict cheapest is about $698, but it takes 17 stops, some buying a gallon to save cents. By default I charge a $5 penalty per stop. That gives 6 practical stops for about 1% more. It's a parameter, and the algorithm itself is a pluggable strategy."
6. Quickly show **POST JSON** and **Coordinates + half tank**, then **Error: outside USA** (400).
   > "It accepts JSON or query params, City-and-State or lat/lng, and gives clean errors."

## 1:40 – 4:20 · Architecture and code walkthrough

1. **`docs/architecture.md`, component diagram** (25 s):
   > "It's a hexagonal architecture inside a single Django app. The domain is pure Python: the value objects, the ports as typing Protocols, and the optimizer. The application layer has one use case, PlanTrip. Infrastructure holds the adapters: OSRM, the geocoders, the spatial index and the ORM repository. The API layer is thin. Dependencies only point inward."
2. **`container.py`** (20 s):
   > "This is the composition root. It's the only place that knows the concrete classes. The patterns you can see here: a Chain of Responsibility for geocoding (coordinates, then an offline Census gazetteer, then Nominatim only for free text), Decorators for caching, and a lazy Proxy for the station index. There's no DI framework; fifteen lines of constructor injection are clearer."
3. **`application/plan_trip.py`** (25 s):
   > "The use case is the whole pipeline: resolve, one routing call, a corridor search, then the strategy. It meters external calls and times each stage, which is the meta block you saw in Postman. The cached decorator keys plans by the command and the dataset version. So when prices are reloaded by the management command, running workers never serve stale plans, without a restart."
4. **`domain/optimizer.py`** (45 s), the core:
   > "This is the fixed-path gas station problem. The greedy is the textbook optimal one for pure cost, but it makes micro-stops. Production uses this DP over station and fuel level, minimizing cost plus a stop penalty. The inner minimum is a running prefix minimum, so it's linear per station, about 20 ms for a whole trip. Both are Strategies behind a port, selected through a small registry."
5. **`infrastructure/station_index.py`** (15 s):
   > "This is a uniform grid of quarter-degree cells. The route is resampled every mile, and each station gets its mile marker along the route. That's about 50 ms coast to coast, with no PostGIS needed. PostGIS would just be another adapter."
6. **`docs/adr/` and `tests/test_architecture.py`** (30 s):
   > "Every significant decision has an ADR in MADR format, with the options considered, the consequences, and when to revisit it. The architecture is enforced, not just documented: this test parses the imports and fails CI if the domain imports Django or the application imports infrastructure. On top of that, the DP is checked against the greedy oracle on 25 random routes, and every plan is replayed so the tank never goes negative."
   Show `uv run pytest`: **93 passed in under a second.** If there is time, mention the load test: about 900 RPS at p95 160 ms on a realistic mix per node, about 6,300 RPS for ETag revalidations, and 0 wrong answers in about 1.7M validated requests (`docs/load-test-report.md`).

## 4:20 – 5:00 · Wrap-up

> "Trade-offs: stations sit at their city centroid, which the 10-mile corridor absorbs. The data has almost no West Coast stations, so a trip like LA to Seattle correctly returns 422. For production I'd swap the local cache for Redis, self-host OSRM, and possibly move the corridor query to PostGIS. Everything is configurable through environment variables. Thanks for watching!"

---

### If something goes wrong live

- **OSRM is slow or down:** the API returns a clean 502. Say it's the public demo server and re-send, since the retry and cache help.
- **You're running over time:** skip `station_index.py` and the POST request.
