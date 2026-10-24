#!/usr/bin/env bash
# Reproduce the load-test report: fake OSRM + production-like gunicorn + Locust scenarios.
# Prereq (once): uv run python loadtest/record_osrm.py
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p loadtest/results
HOST=http://127.0.0.1:8001
WORKERS=${WORKERS:-8}
LOCUST="uv run --group load locust -f loadtest/locustfile.py --headless --host $HOST --only-summary"

start_stack() {  # $1 = extra env (e.g. CACHE_TTL_SECONDS=0)
  uv run python loadtest/fake_osrm.py --port 5001 --latency-ms "${OSRM_LATENCY_MS:-250}" & OSRM_PID=$!
  env $1 DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS=127.0.0.1 OSRM_URL=http://127.0.0.1:5001 GEOCODER_FALLBACK=0 \
    uv run --group load gunicorn config.wsgi -w "$WORKERS" -k gthread --threads "${THREADS:-4}" \
    -b 127.0.0.1:8001 --backlog 4096 --log-level warning & APP_PID=$!
  until curl -sf $HOST/api/v1/health/ >/dev/null; do sleep 0.5; done
}
stop_stack() { kill "$APP_PID" "$OSRM_PID" 2>/dev/null || true; wait 2>/dev/null || true; }
trap stop_stack EXIT

start_stack ""
$LOCUST -u 300 -r 100 -t 60s --processes 4 --csv loadtest/results/1_warm --html loadtest/results/1_warm.html WarmUser
$LOCUST -u 100 -r 50 -t 60s --processes 4 --csv loadtest/results/2_compute --html loadtest/results/2_compute.html ComputeUser
$LOCUST -u 500 -r 100 -t 90s --processes 4 --csv loadtest/results/3_mixed --html loadtest/results/3_mixed.html MixedUser
for u in 25 50 100 200; do
  $LOCUST -u $u -r $u -t 30s --processes 4 --csv loadtest/results/4_step_$u MixedUser
done
$LOCUST -u 2000 -r 1000 -t 60s --processes 6 --csv loadtest/results/5_spike --html loadtest/results/5_spike.html MixedUser || true
$LOCUST -u 2000 -r 200 -t 75s --processes 6 --csv loadtest/results/5b_spike_ramped --html loadtest/results/5b_spike_ramped.html MixedUser || true
$LOCUST -u 25 -r 25 -t 20s --processes 2 --csv loadtest/results/6_recovery MixedUser
stop_stack

THREADS=8 start_stack "CACHE_TTL_SECONDS=0"  # I/O-bound: more threads to overlap OSRM waits
$LOCUST -u 100 -r 50 -t 60s --processes 4 --csv loadtest/results/7_cold --html loadtest/results/7_cold.html ComputeUser
