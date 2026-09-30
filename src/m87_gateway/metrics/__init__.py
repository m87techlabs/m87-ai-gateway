from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest


class GatewayMetrics:
    """Per-process, bounded-label metrics. Prompt text and request IDs are never labels."""

    def __init__(self):
        self.registry = CollectorRegistry()
        labels = ("app_id", "provider", "status_code")
        self.requests = Counter(
            "m87_gateway_requests_total",
            "Completed chat requests",
            labels,
            registry=self.registry,
        )
        self.latency = Histogram(
            "m87_gateway_request_latency_seconds",
            "Total chat request duration",
            ("provider",),
            registry=self.registry,
        )
        self.provider_requests = Counter(
            "m87_gateway_provider_requests_total",
            "Provider adapter attempts",
            ("provider",),
            registry=self.registry,
        )
        self.provider_errors = Counter(
            "m87_gateway_provider_errors_total",
            "Failed provider adapter attempts",
            ("provider",),
            registry=self.registry,
        )
        self.blocks = Counter(
            "m87_gateway_guardrail_blocks_total",
            "Blocked requests",
            ("reason",),
            registry=self.registry,
        )
        self.tokens = Counter(
            "m87_gateway_tokens_total",
            "Provider-reported token usage",
            ("provider", "kind"),
            registry=self.registry,
        )
        self.log_errors = Counter(
            "m87_gateway_log_sink_errors_total",
            "Failed writes to the traffic file",
            registry=self.registry,
        )

    def observe(self, event: dict) -> None:
        provider = event.get("provider") or "none"
        self.requests.labels(
            event.get("app_id") or "anonymous",
            provider,
            str(event["status_code"]),
        ).inc()
        self.latency.labels(provider).observe(event["latency_ms"] / 1000)
        if event.get("provider_attempted"):
            self.provider_requests.labels(provider).inc()
            if event["status_code"] >= 400:
                self.provider_errors.labels(provider).inc()
        if event.get("guardrail_action") == "block":
            self.blocks.labels(event["guardrail_reason"]).inc()
        for kind in ("prompt", "completion"):
            value = event.get(f"{kind}_tokens")
            if value is not None:
                self.tokens.labels(provider, kind).inc(value)

    def render(self) -> bytes:
        return generate_latest(self.registry)
