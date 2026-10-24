"""Local stand-in for OSRM serving recorded responses, with configurable latency.

    uv run python loadtest/fake_osrm.py --port 5001 --latency-ms 300

Point the app at it with OSRM_URL=http://127.0.0.1:5001. Unknown coordinates return
OSRM's own "NoRoute" payload, which the app maps to 502 like a real provider error.
"""

import argparse
import gzip
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

FIXTURES = Path(__file__).parent / "fixtures" / "osrm_routes.json.gz"
PREFIX = "/route/v1/driving/"


def build_handler(routes: dict[str, bytes], latency_s: float):
    no_route = json.dumps({"code": "NoRoute", "message": "Not recorded"}).encode()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 (stdlib API)
            path = unquote(urlsplit(self.path).path)  # urlparse would split ";" off as params
            body = routes.get(path.removeprefix(PREFIX), no_route) if path.startswith(PREFIX) else no_route
            if latency_s:
                time.sleep(latency_s)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence per-request logging under load
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--latency-ms", type=float, default=0)
    args = parser.parse_args()

    routes = {k: json.dumps(v).encode() for k, v in json.loads(gzip.decompress(FIXTURES.read_bytes())).items()}
    ThreadingHTTPServer.request_queue_size = 1024  # default backlog of 5 drops connections under load
    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(routes, args.latency_ms / 1000))
    server.daemon_threads = True
    print(f"fake OSRM on :{args.port} with {len(routes)} routes, latency {args.latency_ms} ms", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
