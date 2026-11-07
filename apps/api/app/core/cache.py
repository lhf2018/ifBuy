"""Simple process-wide TTL memory cache for hot API reads."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def cache_get(key: str) -> Any | None:
    with _lock:
        row = _store.get(key)
        if not row:
            return None
        expires, value = row
        if time.time() >= expires:
            _store.pop(key, None)
            return None
        return value


def cache_set(key: str, value: Any, ttl: float) -> None:
    with _lock:
        _store[key] = (time.time() + max(ttl, 0.1), value)


def cache_delete_prefix(prefix: str) -> None:
    with _lock:
        for k in [k for k in _store if k.startswith(prefix)]:
            _store.pop(k, None)


def cache_clear() -> None:
    with _lock:
        _store.clear()


def cached(key: str, ttl: float, factory: Callable[[], T]) -> T:
    hit = cache_get(key)
    if hit is not None:
        return hit  # type: ignore[return-value]
    value = factory()
    cache_set(key, value, ttl)
    return value
