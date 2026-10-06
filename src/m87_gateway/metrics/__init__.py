from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


class GatewayMetrics:
    """Per-process, bounded-label metrics. Prompt text and request IDs are never labels."""

    def __init__(self):
        self.registry = CollectorRegistry()
        self.queue_depth = Gauge(
            "m87_gateway_queue_depth",
            "Requests awaiting concurrency admission",
            registry=self.registry,
        )
        self.queue_wait = Histogram(
            "m87_gateway_queue_wait_seconds",
            "Time spent awaiting concurrency admission",
            ("outcome",),
            registry=self.registry,
        )
        self.streams = Counter(
            "m87_gateway_streams_total",
            "Final streaming outcomes",
            ("provider", "outcome"),
            registry=self.registry,
        )
        self.cancellations = Counter(
            "m87_gateway_cancellations_total",
            "Cancelled chat requests",
            ("provider",),
            registry=self.registry,
        )
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
        self.cache_requests = Counter(
            "m87_gateway_cache_requests_total",
            "Exact-response cache lookups",
            ("status",),
            registry=self.registry,
        )
        self.provider_retries = Counter(
            "m87_gateway_provider_retries_total",
            "Retried provider adapter attempts",
            ("provider",),
            registry=self.registry,
        )
        self.rate_limits = Counter(
            "m87_gateway_rate_limit_rejections_total",
            "Requests rejected by per-app rate limits",
            ("app_id",),
            registry=self.registry,
        )

        self.concurrency_limits = Counter(
            "m87_gateway_concurrency_limit_rejections_total",
            "Requests rejected by gateway or application concurrency limits",
            ("app_id",),
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
        outcome = event.get("request_outcome")
        if event.get("streaming") and outcome in {"completed", "failed", "cancelled"}:
            self.streams.labels(provider, outcome).inc()
        if outcome == "cancelled":
            self.cancellations.labels(provider).inc()
        attempts = event.get("provider_attempts", 0) or (
            1 if event.get("provider_attempted") else 0
        )
        if attempts:
            self.provider_requests.labels(provider).inc(attempts)
            retries = event.get("provider_retries", 0)
            failures = retries + (
                1 if event["status_code"] >= 400 and outcome != "cancelled" else 0
            )
            if failures:
                self.provider_errors.labels(provider).inc(failures)
            if retries:
                self.provider_retries.labels(provider).inc(retries)
        if event.get("guardrail_action") == "block":
            self.blocks.labels(event["guardrail_reason"]).inc()
        for kind in ("prompt", "completion"):
            value = event.get(f"{kind}_tokens")
            if value is not None and event.get("cache_status") != "hit":
                self.tokens.labels(provider, kind).inc(value)
        cache_status = event.get("cache_status")
        if cache_status in {"hit", "miss"}:
            self.cache_requests.labels(cache_status).inc()
        if event.get("error_type") == "rate_limit_exceeded":
            self.rate_limits.labels(event.get("app_id") or "anonymous").inc()

        if event.get("error_type") in {"concurrency_limit_exceeded", "queue_full", "queue_timeout"}:
            self.concurrency_limits.labels(event.get("app_id") or "anonymous").inc()

    def render(self) -> bytes:
        return generate_latest(self.registry)
