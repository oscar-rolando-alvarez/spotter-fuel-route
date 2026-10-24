"""Shared outbound HTTP: one pooled session, bounded retries, per-request call accounting."""

from functools import lru_cache

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fuel_route.application.metering import record_external_call
from fuel_route.domain.errors import ProviderUnavailableError


@lru_cache(maxsize=4)
def session(user_agent: str) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.3, status_forcelist=(429, 502, 503, 504), allowed_methods={"GET"})
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=10))
    s.headers["User-Agent"] = user_agent
    return s


class JsonHttpClient:
    """Thin GET-JSON client. Translates every transport failure into a domain error."""

    def __init__(self, user_agent: str, timeout_seconds: float):
        self._user_agent = user_agent
        self._timeout = timeout_seconds

    def get_json(self, url: str, params: dict | None = None) -> dict | list:
        record_external_call()
        try:
            resp = session(self._user_agent).get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderUnavailableError(f"{url}: {exc}") from exc
