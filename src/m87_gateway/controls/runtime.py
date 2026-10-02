from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict, deque
from copy import deepcopy
from typing import Any


class SlidingWindowRateLimiter:
    """Bound request starts per app in a local rolling 60-second window."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, app_id: str, limit: int | None) -> int | None:
        if limit is None:
            return None
        now = self._clock()
        cutoff = now - 60
        with self._lock:
            entries = self._requests.setdefault(app_id, deque())
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= limit:
                return max(1, int(60 - (now - entries[0]) + 0.999))
            entries.append(now)
        return None


class ExactResponseCache:
    """Thread-safe, per-app, in-memory LRU cache with a fixed TTL."""

    def __init__(self, enabled: bool, ttl_seconds: int, max_entries: int, clock=time.monotonic):
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(app_id: str, routed_model: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"app_id": app_id, "routed_model": routed_model, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        now = self._clock()
        with self._lock:
            stored = self._entries.get(key)
            if stored is None:
                return None
            expires_at, value = stored
            if expires_at <= now:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return deepcopy(value)

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._entries[key] = (self._clock() + self.ttl_seconds, deepcopy(value))
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
