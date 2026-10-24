"""Single-flight: concurrent callers asking for the same key share one computation.

Prevents a cache stampede: when a popular key is missing, N simultaneous requests would
otherwise each call OSRM (breaking the one-call budget) or recompute the same plan.
Scope is one process; across workers the worst case is one call per worker.
"""

import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class SingleFlight:
    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def do(self, key: str, lookup: Callable[[], T | None], compute: Callable[[], T]) -> T:
        """Return ``lookup()`` if present; otherwise ``compute()`` once per key at a time."""
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        try:
            with lock:
                # Re-check inside the lock: a concurrent caller may have filled the cache.
                if (hit := lookup()) is not None:
                    return hit
                return compute()
        finally:
            with self._guard:
                if self._locks.get(key) is lock and not lock.locked():
                    del self._locks[key]
