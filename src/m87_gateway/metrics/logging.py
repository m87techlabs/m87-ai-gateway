"""Scrape-time health snapshots; never expose destination URLs, credentials or text."""

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily


class LoggingCollector:
    def __init__(self, recorder, exporter):
        self.recorder = recorder
        self.exporter = exporter

    def collect(self):
        local = self.recorder.health()
        writes = CounterMetricFamily(
            "m87_gateway_log_writes",
            "Local log writes since process start",
            labels=["destination", "outcome"],
        )
        healthy = GaugeMetricFamily(
            "m87_gateway_log_last_write_ok",
            "Last completed local write; absent before first write",
            labels=["destination"],
        )
        for item in local["items"]:
            destination = item["destination"]
            if destination not in {"control_store", "private_jsonl"}:
                continue
            for outcome, field in (("success", "successful_writes"), ("failure", "failed_writes")):
                writes.add_metric([destination, outcome], item[field])
            if item["last_write_ok"] is not None:
                healthy.add_metric([destination], int(item["last_write_ok"]))
        yield writes
        yield healthy
        report = self.exporter().health()
        for suffix, help_text, value in (
            ("enabled", "Whether remote metadata export is enabled", report["enabled"]),
            (
                "storage_ok",
                "Whether export storage was readable and worker storage is healthy",
                report["storage_ok"],
            ),
        ):
            yield GaugeMetricFamily(f"m87_gateway_log_export_{suffix}", help_text, value=int(value))
        # Failed storage snapshots omit counts rather than replacing unknown values with zero.
        if not report["storage_ok"]:
            return
        for field in (
            "pending",
            "held_for_other_destination",
            "awaiting_expiry",
            "oldest_pending_at",
            "max_pending",
        ):
            value = report.get(field)
            if value is not None:
                yield GaugeMetricFamily(
                    f"m87_gateway_log_export_{field}",
                    "Export queue snapshot: " + field,
                    value=value,
                )
        for field in ("delivered", "failed_attempts", "dropped", "expired"):
            if field in report:
                yield CounterMetricFamily(
                    f"m87_gateway_log_export_{field}",
                    "Persisted export counter: " + field,
                    value=report[field],
                )
