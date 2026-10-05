from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from collections import OrderedDict, deque
from copy import deepcopy
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from dataclasses import dataclass

from m87_gateway.api.errors import GatewayError


@dataclass(eq=False)
class QueuedRequest:
    app_id: str
    global_limit: int
    app_limit: int | None
    event: asyncio.Event
    loop: asyncio.AbstractEventLoop


class InFlightLimiter:
    """Optional bounded FIFO admission; earlier eligible requests take capacity first."""

    def __init__(self, metrics=None):
        self._metrics = metrics
        self._pending: deque[QueuedRequest] = deque()
        self._apps: dict[str, int] = {}
        self._total = 0
        self._lock = threading.Lock()

    @contextmanager
    def admit(self, app_id: str, global_limit: int, app_limit: int | None):
        with self._lock:
            count = self._apps.get(app_id, 0)
            if (
                self._total >= global_limit
                or (app_limit is not None and count >= app_limit)
                or any(self._eligible(item) for item in self._pending)
            ):
                raise GatewayError(
                    429,
                    "concurrency_limit_exceeded",
                    "Gateway concurrent request limit exceeded",
                    "rate_limit_error",
                    headers={"Retry-After": "1"},
                )
            self._total += 1
            self._apps[app_id] = count + 1
        try:
            yield
        finally:
            self._release(app_id)

    def _eligible(self, item: QueuedRequest) -> bool:
        return self._total < item.global_limit and (
            item.app_limit is None or self._apps.get(item.app_id, 0) < item.app_limit
        )

    def _wake(self) -> None:
        for item in self._pending:
            item.loop.call_soon_threadsafe(item.event.set)
        if self._metrics is not None:
            self._metrics.queue_depth.set(len(self._pending))

    def _release(self, app_id: str) -> None:
        with self._lock:
            self._total -= 1
            remaining = self._apps[app_id] - 1
            if remaining:
                self._apps[app_id] = remaining
            else:
                del self._apps[app_id]
            self._wake()

    @asynccontextmanager
    async def admit_wait(
        self,
        app_id: str,
        global_limit: int,
        app_limit: int | None,
        queue_max_depth: int = 0,
        queue_max_depth_per_app: int = 16,
        queue_wait_timeout_seconds: float = 10,
        disconnected=None,
        audit=None,
    ):
        item = QueuedRequest(
            app_id, global_limit, app_limit, asyncio.Event(), asyncio.get_running_loop()
        )
        started = time.monotonic()
        acquired = False
        queued = False
        outcome = "immediate"
        wait = 0.0
        try:
            with self._lock:
                earlier = any(self._eligible(pending) for pending in self._pending)
                if self._eligible(item) and not earlier:
                    self._total += 1
                    self._apps[app_id] = self._apps.get(app_id, 0) + 1
                    acquired = True
                elif queue_max_depth == 0:
                    raise GatewayError(
                        429,
                        "concurrency_limit_exceeded",
                        "Gateway concurrent request limit exceeded",
                        "rate_limit_error",
                        headers={"Retry-After": "1"},
                    )
                elif (
                    len(self._pending) >= queue_max_depth
                    or sum(p.app_id == app_id for p in self._pending) >= queue_max_depth_per_app
                ):
                    outcome = "full"
                    if self._metrics is not None:
                        self._metrics.queue_wait.labels(outcome).observe(0)
                    raise GatewayError(
                        429,
                        "queue_full",
                        "Gateway request queue is full",
                        "rate_limit_error",
                        headers={"Retry-After": "1"},
                    )
                else:
                    self._pending.append(item)
                    queued = True
                    self._wake()
            while not acquired:
                if disconnected is not None and await disconnected():
                    outcome = "cancelled"
                    raise asyncio.CancelledError()
                wait = time.monotonic() - started
                if wait >= queue_wait_timeout_seconds:
                    outcome = "timeout"
                    raise GatewayError(
                        429,
                        "queue_timeout",
                        "Gateway request queue wait expired",
                        "rate_limit_error",
                        headers={"Retry-After": "1"},
                    )
                with self._lock:
                    first = next(
                        (pending for pending in self._pending if self._eligible(pending)), None
                    )
                    if first is item:
                        self._pending.remove(item)
                        self._total += 1
                        self._apps[app_id] = self._apps.get(app_id, 0) + 1
                        acquired = True
                        outcome = "admitted"
                        self._wake()
                    item.event.clear()
                if not acquired:
                    try:
                        await asyncio.wait_for(
                            item.event.wait(), timeout=min(0.05, queue_wait_timeout_seconds - wait)
                        )
                    except TimeoutError:
                        pass
            if audit is not None:
                audit.update(queue_wait_ms=round(wait * 1000, 3), queue_outcome=outcome)
            if queued and self._metrics is not None:
                self._metrics.queue_wait.labels("admitted").observe(wait)
            yield
        except asyncio.CancelledError:
            if not acquired:
                outcome = "cancelled"
            raise
        finally:
            if acquired:
                self._release(app_id)
            elif queued:
                wait = time.monotonic() - started
                with self._lock:
                    self._pending.remove(item)
                    self._wake()
                if self._metrics is not None:
                    self._metrics.queue_wait.labels(outcome).observe(wait)
            if not acquired and audit is not None:
                audit.update(queue_wait_ms=round(wait * 1000, 3), queue_outcome=outcome)

    def snapshot(self):
        with self._lock:
            return {"active_requests": self._total, "queued_requests": len(self._pending)}


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

    def clear(self):
        with self._lock:
            self._entries.clear()
