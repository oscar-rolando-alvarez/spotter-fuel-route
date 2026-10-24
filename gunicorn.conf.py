"""gunicorn settings for containers. Every value can be overridden through the environment.

Sizing (docs/load-test-report.md): the work is CPU-bound Python, so one worker per vCPU;
threads overlap the OSRM wait on cold requests. 8 workers x 4 threads sustained ~900 RPS
at p95 160 ms on the mixed scenario.
"""

import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", multiprocessing.cpu_count()))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 4))
backlog = int(os.environ.get("GUNICORN_BACKLOG", 2048))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 30))  # OSRM timeout is 15 s; leave room for retries
graceful_timeout = 20
keepalive = 5
# Worker recycling is off by default: RSS stayed flat under ~1.7M load-test requests, and at
# ~9k RPS a 20k-request limit restarted workers every ~18 s and reset pooled keep-alive
# connections (0.05% errors). Set GUNICORN_MAX_REQUESTS if a leak ever shows up.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", 0))
max_requests_jitter = max_requests // 10
accesslog = "-" if os.environ.get("GUNICORN_ACCESS_LOG", "0") == "1" else None
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
# Workers write temp heartbeat files; /dev/shm avoids slow overlay filesystems in Docker.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None
# The control socket defaults to ~/.gunicorn; the container filesystem is read-only, /tmp is tmpfs.
control_socket = os.environ.get("GUNICORN_CONTROL_SOCKET", "/tmp/gunicorn.ctl")


def post_worker_init(worker):
    """Warm each worker before it takes traffic: wire the container, load the US border,
    build the station grid. Otherwise the first request per worker pays ~20 ms for it."""
    try:
        from fuel_route.container import get_container

        container = get_container()
        worker.log.info("warmed: %d stations indexed", container.station_index.size)
    except Exception:  # never block boot on warm-up; requests would build lazily anyway
        worker.log.exception("warm-up failed; continuing with lazy initialization")
