"""Per-use-case metering of outbound calls.

Lives in the application layer so the use case can report it without importing
infrastructure; adapters (outer ring) increment it, which respects the dependency rule.
"""

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_external_calls: contextvars.ContextVar[int] = contextvars.ContextVar("external_calls", default=0)


def record_external_call() -> None:
    _external_calls.set(_external_calls.get() + 1)


@contextmanager
def metered() -> Iterator[contextvars.ContextVar[int]]:
    token = _external_calls.set(0)
    try:
        yield _external_calls
    finally:
        _external_calls.reset(token)
