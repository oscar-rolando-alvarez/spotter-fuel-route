"""Shared HTTP session for the (few) outbound calls, with retries and call accounting."""

import contextvars
from functools import lru_cache

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Counts outbound API calls within one request so the response can report it.
external_calls: contextvars.ContextVar[int] = contextvars.ContextVar("external_calls", default=0)


class UpstreamError(Exception):
    """An external map/routing provider failed or returned something unusable."""


@lru_cache(maxsize=1)
def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.3, status_forcelist=(429, 502, 503, 504), allowed_methods={"GET"})
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=10))
    s.headers["User-Agent"] = settings.FUEL_ROUTE["USER_AGENT"]
    return s


def get_json(url: str, params: dict | None = None) -> dict | list:
    external_calls.set(external_calls.get() + 1)
    try:
        resp = session().get(url, params=params, timeout=settings.FUEL_ROUTE["HTTP_TIMEOUT_SECONDS"])
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamError(f"{url}: {exc}") from exc
