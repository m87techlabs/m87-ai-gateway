"""Trusted exporter registry and asynchronous, bounded webhook delivery."""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Protocol

import httpx

from .outbox import DeliveryOutbox, destination_binding


class LogExporter(Protocol):
    async def send(self, delivery_id: str, event: dict) -> bool: ...
    async def close(self) -> None: ...


class WebhookExporter:
    def __init__(self, config, token):
        self.config = config
        self.client = httpx.AsyncClient(
            timeout=config.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )

    async def send(self, delivery_id, event):
        # Streaming the response headers avoids loading an unbounded remote body.
        async with self.client.stream(
            "POST",
            self.config.endpoint,
            headers={"Idempotency-Key": delivery_id},
            json={"schema_version": 1, "delivery_id": delivery_id, "event": event},
        ) as response:
            return 200 <= response.status_code < 300

    async def close(self):
        await self.client.aclose()


class LokiExporter(WebhookExporter):
    """Loki JSON push with fixed labels and stable event timestamps across retries."""

    async def send(self, delivery_id, event):
        created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("Loki event requires a timezone-aware timestamp")
        delta = created - datetime(1970, 1, 1, tzinfo=timezone.utc)
        nanoseconds = ((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds) * 1000
        line = json.dumps(
            {**event, "schema_version": 1, "delivery_id": delivery_id},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        async with self.client.stream(
            "POST",
            self.config.endpoint,
            json={
                "streams": [
                    {
                        "stream": {"service_name": "m87-ai-gateway", "log_kind": "llm_exchange"},
                        "values": [[str(nanoseconds), line]],
                    }
                ]
            },
        ) as response:
            # Loki can return 260 (or configured 200) when ingestion is blocked.
            return response.status_code == 204


_EXPORTERS = {"webhook": WebhookExporter, "loki": LokiExporter}


def exporter_adapters():
    return tuple(sorted(_EXPORTERS))


def resolve_export_token(config, store, override=None):
    if override is not None:
        token = override
    elif config.use_stored_key:
        get_key = getattr(getattr(store, "secrets", None), "get_export_key", None)
        if not callable(get_key):
            raise ValueError("Backend does not support stored export credentials")
        token = get_key(destination_binding(config)) or ""
    else:
        token = os.getenv(config.api_key_env, "") if config.api_key_env else ""
    if (config.use_stored_key or config.api_key_env) and not token:
        raise ValueError("Log exporter credential is unavailable")
    if token and (len(token) > 4096 or any(not 33 <= ord(c) <= 126 for c in token)):
        raise ValueError("Log exporter credential is invalid")
    return token


def register_log_exporter(name, factory):
    """Register trusted source extensions before application startup; no config imports."""
    if (
        not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name)
        or name in _EXPORTERS
        or not callable(factory)
    ):
        raise ValueError("Invalid or duplicate log exporter adapter")
    _EXPORTERS[name] = factory


class ExportService:
    def __init__(self, config, store, recorder, *, token_override=None, configure_outbox=True):
        self.config = config
        self.outbox = getattr(store, "export_outbox", None)
        self.exporter = None
        self.task = None
        self.storage_ok = True
        self.recorder = recorder
        if configure_outbox and isinstance(self.outbox, DeliveryOutbox):
            self.outbox.configure(config, recorder.redact)
        if not config.enabled:
            return
        if not isinstance(self.outbox, DeliveryOutbox):
            raise ValueError("Backend does not implement the delivery outbox contract")
        factory = _EXPORTERS.get(config.adapter)
        if factory is None:
            raise ValueError("Log exporter adapter is not registered")
        token = resolve_export_token(config, store, token_override)
        if token:
            recorder.add_secret(token)
        self.exporter = factory(config, token)
        if not callable(getattr(self.exporter, "send", None)) or not callable(
            getattr(self.exporter, "close", None)
        ):
            raise ValueError("Log exporter does not implement the delivery contract")

    def start(self):
        if self.exporter:
            self.task = asyncio.create_task(self._run())

    async def deliver_once(self):
        item = await asyncio.to_thread(self.outbox.claim)
        if item is None:
            return False
        if item["binding"] != destination_binding(self.config):
            return False  # A retired worker must never send a claim from a new binding.
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                success = await self.exporter.send(item["delivery_id"], json.loads(item["payload"]))
        except Exception:
            success = False
        await asyncio.to_thread(self.outbox.complete, item, success=success)
        return True

    async def _run(self):
        while True:
            try:
                worked = await self.deliver_once()
                self.storage_ok = True
            except Exception:
                # A broken/locked disk must not terminate the worker or leak exception details.
                self.storage_ok = False
                worked = False
            await asyncio.sleep(0 if worked else self.config.poll_seconds)

    def health(self):
        report = {
            "enabled": self.config.enabled,
            "adapter": self.config.adapter,
            "content_export": False,
            "storage_ok": self.storage_ok,
            "max_pending": self.config.max_pending,
            "retention_hours": self.config.retention_hours,
            "scope": "Metadata only; at-least-once after local commit. Receiver must deduplicate delivery_id. Counters persist across restart.",
        }
        if isinstance(self.outbox, DeliveryOutbox):
            try:
                report.update(self.outbox.health())
            except Exception:
                report["storage_ok"] = False
        last_success = report.get("last_success_at") or 0
        last_failure = report.get("last_failure_at") or 0
        report["delivery_state"] = (
            "disabled"
            if not self.config.enabled
            else "storage_unavailable"
            if not report["storage_ok"]
            else "retrying"
            if last_failure > last_success
            else "healthy"
            if last_success
            else "not_delivered_yet"
        )
        return report

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.exporter:
            await self.exporter.close()


async def activate_export(request, settings, service):
    """Publish validated settings and worker together, then retire the previous worker."""
    from m87_gateway.control.setup import activate

    state = request.app.state
    old = state.log_export
    if old.task:
        old.task.cancel()
    service.outbox.configure(service.config, state.recorder.redact)
    state.log_export = service
    activate(request, settings)
    service.start()
    try:
        async with asyncio.timeout(5):
            await old.close()
    except Exception:
        state.recorder.logger.error(json.dumps({"event": "log_export_cleanup_failed"}))
