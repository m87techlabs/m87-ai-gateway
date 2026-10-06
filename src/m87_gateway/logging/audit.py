import json
import logging
import os
import re
import stat
import sys
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Protocol

from m87_gateway.config import GatewaySettings
from m87_gateway.private_storage import prepare_file
from m87_gateway.adapters import adapters
from m87_gateway.metrics import GatewayMetrics

REDACTED = "[REDACTED]"
CREDENTIAL_PATTERN = re.compile(
    r"(?i)\bbearer\s+[a-z0-9._~+/=-]+|\bsk-[a-z0-9_-]{8,}|\bm87_[a-z0-9_-]{8,}"
)


class EventSink(Protocol):
    """Local sink boundary; remote exporters should consume sanitized events asynchronously."""

    def emit(self, event: dict) -> None: ...
    def close(self) -> None: ...


class PrivateRotatingHandler(RotatingFileHandler):
    def _open(self):
        if Path(self.baseFilename).is_symlink():
            raise OSError("Traffic log cannot be a symlink")
        prepare_file(Path(self.baseFilename))
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(
            self.baseFilename,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | no_follow,
            0o600,
        )
        if os.name != "nt" and stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
            os.close(descriptor)
            raise ValueError("Traffic log files must have owner-only permissions")
        return os.fdopen(descriptor, "a", encoding="utf-8")

    def handleError(self, record):
        # Standard logging may dump the record to stderr. Never expose captured content that way.
        raise OSError("Traffic log write failed") from None


class JsonFileSink:
    def __init__(self, path: str, max_bytes: int, backup_count: int):
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.handler = PrivateRotatingHandler(
            destination,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        self.handler.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, event: dict) -> None:
        record = logging.LogRecord(
            "m87_gateway.traffic",
            logging.INFO,
            "",
            0,
            json.dumps(event),
            (),
            None,
        )
        self.handler.handle(record)

    def close(self) -> None:
        self.handler.close()


class AuditRecorder:
    def __init__(
        self,
        settings: GatewaySettings,
        metrics: GatewayMetrics,
        control_sink: EventSink | None = None,
    ):
        self.settings = settings
        self.metrics = metrics
        self.logger = logging.Logger("m87_gateway.audit", level=logging.INFO)
        self.logger.propagate = False
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)
        secret_values = [app.api_key for app in settings.configured_apps]
        for name in adapters():
            variable = settings.providers.for_adapter(name).api_key_env
            if variable and os.getenv(variable):
                secret_values.append(os.environ[variable])
        if control_sink is not None and hasattr(control_sink, "provider_secret_values"):
            secret_values.extend(control_sink.provider_secret_values())
        self.secrets = sorted(set(secret_values), key=len, reverse=True)
        config = settings.observability.traffic_log
        self.sink: EventSink | None = (
            JsonFileSink(config.path, config.max_bytes, config.backup_count)
            if config.path
            else None
        )
        self.sinks = [sink for sink in (self.sink, control_sink) if sink is not None]
        self._health_lock = threading.Lock()
        self._sink_health = {
            id(sink): {
                "destination": "private_jsonl" if sink is self.sink else "control_store",
                "successful_writes": 0,
                "failed_writes": 0,
                "last_write_ok": None,
                "last_success_at": None,
                "last_failure_at": None,
            }
            for sink in self.sinks
        }

    def add_secret(self, value: str) -> None:
        if value not in self.secrets:
            self.secrets = sorted([*self.secrets, value], key=len, reverse=True)

    def redact(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, REDACTED)
            return CREDENTIAL_PATTERN.sub(REDACTED, value)
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        return value

    def content(self, value, max_content_chars=None) -> tuple[str, bool]:
        # Redact before truncation so a boundary cannot reveal a partial known credential.
        serialized = json.dumps(self.redact(value), ensure_ascii=False)
        limit = (
            max_content_chars
            if max_content_chars is not None
            else self.settings.observability.traffic_log.max_content_chars
        )
        return serialized[:limit], len(serialized) > limit

    def record(
        self, metadata: dict, request_content=None, response_content=None, max_content_chars=None
    ) -> None:
        event = self.redact(metadata)
        # These public identities come from server-side app configuration, not request content.
        # Credential-shaped names must remain stable for project/accounting queries.
        for name in ("app_id", "project_id"):
            value = metadata.get(name)
            if isinstance(value, str):
                for secret in self.secrets:
                    value = value.replace(secret, REDACTED)
                event[name] = value
        if self.settings.observability.json_logs:
            self.logger.info(json.dumps(event))
        if not self.sinks:
            return
        stored = dict(event)
        for name, value in (
            ("request_content", request_content),
            ("response_content", response_content),
        ):
            if value is not None:
                stored[name], was_truncated = self.content(value, max_content_chars)
                stored[f"{name}_truncated"] = was_truncated or bool(event.get(f"{name}_truncated"))
        for sink in self.sinks:
            try:
                sink.emit(stored)
                self._record_health(sink, True)
            except Exception:
                self._record_health(sink, False)
                if self.settings.observability.prometheus_metrics:
                    self.metrics.log_errors.inc()
                self.logger.error(
                    json.dumps(
                        {
                            "event": "traffic_log_write_failed",
                            "request_id": event["request_id"],
                        }
                    )
                )

    def _record_health(self, sink, ok):
        with self._health_lock:
            item = self._sink_health[id(sink)]
            item["last_write_ok"] = ok
            item["successful_writes" if ok else "failed_writes"] += 1
            item["last_success_at" if ok else "last_failure_at"] = datetime.now(
                timezone.utc
            ).isoformat()

    def health(self) -> dict:
        with self._health_lock:
            items = [dict(item) for item in self._sink_health.values()]
        return {
            "ok": bool(items) and all(item["last_write_ok"] is not False for item in items),
            "capture_enabled": self.settings.observability.traffic_log.capture_content,
            "items": items,
            "scope": "Last completed write per destination; process counters reset on restart. Delivery remains best effort.",
        }

    def close(self) -> None:
        for sink in self.sinks:
            sink.close()
        for handler in self.logger.handlers:
            handler.close()
