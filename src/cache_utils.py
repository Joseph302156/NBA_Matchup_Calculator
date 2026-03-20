"""Thread-safe TTL cache for expensive fetchers (e.g. NBA API)."""
from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_store: dict[str, tuple[object, float]] = {}


def ttl_get(key: str, ttl_sec: float, factory: Callable[[], T]) -> T:
    """
    Return cached value if key is fresh; else call factory() and store.
    ttl_sec <= 0 disables caching (always calls factory).
    """
    if ttl_sec <= 0:
        return factory()
    now = time.time()
    with _lock:
        hit = _store.get(key)
        if hit is not None:
            val, ts = hit
            if now - ts < ttl_sec:
                return val  # type: ignore[return-value]
    val = factory()
    with _lock:
        _store[key] = (val, time.time())
    return val


def ttl_clear(prefix: str | None = None) -> None:
    """Clear all entries, or those whose key starts with prefix (for tests)."""
    with _lock:
        if prefix is None:
            _store.clear()
        else:
            for k in list(_store.keys()):
                if k.startswith(prefix):
                    del _store[k]
