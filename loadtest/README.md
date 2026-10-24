# Load and stress tests

Results and analysis are in [`docs/load-test-report.md`](../docs/load-test-report.md). Design decisions are in [ADR-0012](../docs/adr/0012-performance-under-load.md).

```bash
uv sync --group load                     # gunicorn + locust
uv run python loadtest/record_osrm.py    # once: records 13 real OSRM routes (~15 requests at 1 req/s)
loadtest/run_all.sh                      # ~10 min: all scenarios; reports in loadtest/results/
```

| File | Purpose |
|---|---|
| `trips.py` | Trips under test, with expected status and baseline cost (used for correctness checks) |
| `record_osrm.py` | Records real OSRM responses keyed exactly as the app requests them |
| `fake_osrm.py` | Local OSRM stand-in with configurable latency, so we never stress the public server |
| `locustfile.py` | `WarmUser`, `ComputeUser` and `MixedUser`. Every response is validated, not just its status |
| `run_all.sh` | Starts fake OSRM and gunicorn (8 workers × 4 threads, `DEBUG=0`), then runs every scenario |

Ad-hoc run against a stack you started yourself:

```bash
uv run --group load locust -f loadtest/locustfile.py --host http://127.0.0.1:8001   # web UI on :8089
```
