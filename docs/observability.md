# Observability and LLM traffic

## What is recorded

Every POST to `/v1/chat/completions` produces one `llm_exchange` outcome event,
including auth failures, schema errors, policy rejections, provider errors, and
successful completions. A gateway-generated `X-Request-ID` links the response to
the event. Incoming IDs are not trusted or reused.

Events include schema version, start timestamp, app ID, requested/resolved model,
provider, status, duration, guardrail action/reason, provider attempt, token usage,
and safe error category. Missing usage and unimplemented cost estimates are
`null`. Auth/validation failures may have no known app or model.

Metadata goes to JSON stdout when `observability.json_logs` is enabled.
Headers, credentials, client IPs, prompts, completions, and upstream exception
bodies are absent from this stream. Framework/server access logs are separate;
disable access logging or configure the proxy when URL privacy is required.

## Optional local traffic storage

A rotating JSONL file can retain metadata and, with explicit permission, the
request messages and returned completion choices. Each line is a complete event;
content fields contain bounded JSON text strings. A truncated field is marked
and may no longer be independently parseable as JSON.

Merge this example into your ignored configuration; retain each app's key,
allowlist, and other required settings:

```yaml
apps:
  - app_id: worker-test
    api_key: replace-with-a-private-app-key
    allowed_models: [auto, "ollama:llama3"]
    capture_content: true

observability:
  json_logs: true
  prometheus_metrics: true
  traffic_log:
    path: var/log/gateway/traffic.jsonl
    capture_content: true
    max_content_chars: 16384
    max_bytes: 10485760
    backup_count: 3
```

Both `traffic_log.capture_content` and the app's `capture_content` must be true.
Content capture also requires a private JSONL path or the enabled local control
plane. The shipped example leaves it disabled.
Content is retained only after authentication, final-model authorization, and
request guardrails pass. Failed upstream calls can retain the permitted request,
but do not store upstream error bodies.

The sink creates owner-only files (0600) and new leaf directories (0700) on
POSIX systems. It rejects existing broadly readable log files and symlink targets.
Rotation retains the active file plus the configured number of backups; this
bounds file count/size, not age. Use one gateway process per file. A record can
exceed the rotation threshold, so size is an approximate disk bound.

Known configured app/provider credentials and common bearer/key patterns are
redacted before truncation. This is not general PII or arbitrary-secret detection.
Free-form prompts and responses can still contain sensitive text: enable capture
only for a deliberately selected app and use synthetic data during initial tests.

Native runs can use the relative `var/log/gateway/` path, ignored by Git and
Docker builds. Container files are ephemeral unless that path is mounted on a
private host directory or volume. No volume or remote collector is provisioned
automatically. See the [traffic logging runbook](runbooks/traffic-logging.md).

## Metrics

`GET /metrics` exposes:

- `m87_gateway_requests_total`
- `m87_gateway_request_latency_seconds`
- `m87_gateway_provider_requests_total`
- `m87_gateway_provider_errors_total`
- `m87_gateway_guardrail_blocks_total`
- `m87_gateway_tokens_total`
- `m87_gateway_log_sink_errors_total`
- `m87_gateway_cache_requests_total`
- `m87_gateway_provider_retries_total`
- `m87_gateway_rate_limit_rejections_total`

Events and console rows include cache status, provider attempts, and retries.
Cache hits retain original response usage for inspection but do not increment
provider token metrics or control-plane token totals. Failed retry attempts can
consume upstream tokens that are unavailable to the gateway.

Labels use configured app IDs, known providers, status codes, fixed guardrail
reasons, and token kinds. Request IDs, message text, and arbitrary model strings
are not labels. Adapter-attempt counters include calls that fail before sending
HTTP, such as missing provider credentials. Metrics are per process and reset
on restart; missing token usage contributes no token increments.

Set `prometheus_metrics: false` to disable recording and return 404 from the
endpoint. Keep the endpoint on the operator network; do not expose it through the
public tunnel route.

## Grafana, Loki, and future exporters

Prometheus collects numeric time-series metrics. Loki stores logs; Grafana can
query both. See the official [Prometheus overview](https://prometheus.io/docs/introduction/overview/)
and [Loki overview](https://grafana.com/docs/loki/latest/get-started/overview/).

```mermaid
flowchart LR
    App[Worker or application] --> Gateway[Gateway chat endpoint]
    Gateway --> Provider[Model service]
    Provider --> Gateway
    Gateway --> Metadata[JSON stdout metadata]
    Gateway --> Private[Optional private rotating traffic file]
    Gateway --> Metrics[Metrics endpoint]
    Metrics -. Planned collector .-> Prometheus[Prometheus]
    Metadata -. Planned collector .-> Loki[Loki]
    Private -. Explicit export policy .-> Loki
    Prometheus --> Grafana[Grafana views]
    Loki --> Grafana
```

The in-process `EventSink` protocol is the initial extension boundary. Implemented
sinks are rotating JSONL and the local SQLite control store. A later collector such as
Grafana Alloy or an OpenTelemetry Collector can ship sanitized events without
coupling provider requests to a remote logging service. Exporting captured content
needs a separate explicit destination, access, retention, and redaction policy.

## Reliability limits

Sink writes run in the thread pool after the response is sent. A write failure
increments the sink-error metric and emits a safe metadata error; it does not
turn a successful model response into a failed request. Logs are best effort:
disk failure, abrupt termination, or cancellation can lose an event. There is no
durable queue, replay, remote delivery, or exactly-once delivery. The local
SQLite store and search UI target one instance; provider credentials are encrypted,
while captured LLM content is protected by filesystem permissions rather than
field-level encryption.

The [local control plane](control-plane.md) provides request/token summaries,
event detail, bounded JSON export, key operations, and a destination inventory.

The gateway sees only traffic that passes through it. If the local machine,
Docker, or tunnel is down, a Worker/edge failure occurs before the gateway and
must be recorded at that layer. Streaming, model discovery, embeddings, traces,
cost estimation, and remote exporters remain planned.
