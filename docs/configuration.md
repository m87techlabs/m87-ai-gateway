# Configuration

The gateway loads YAML, applies selected environment overrides, and validates it
at startup. Unknown fields, malformed routes/endpoints, duplicate app IDs/keys,
and invalid limits fail startup. File/environment settings are loaded at startup; saved console settings override
the supported fields and apply to new requests.

## File selection and overrides

The loader uses an explicit code-supplied path, then `M87_GATEWAY_CONFIG` or
`GATEWAY_CONFIG`, then `config.yaml` or `config.example.yaml` in the working
directory. An explicitly selected missing file fails startup. Without a file,
the default configuration has no app keys and denies application access. Ancestor
directories are not searched for demonstration keys.

The loader does not read `.env` itself. Compose injects it; local Uvicorn needs
`--env-file .env` or a configured process environment.

| Variable | Effect |
| --- | --- |
| `M87_GATEWAY_CONFIG` / `GATEWAY_CONFIG` | Select YAML file |
| `GATEWAY_NAME`, `GATEWAY_ENVIRONMENT`, `GATEWAY_LOG_LEVEL` | Parsed gateway metadata; audit events remain at INFO independently |
| `SERVER_HOST`, `SERVER_PORT` | Validated server settings; Uvicorn CLI still selects the actual listener |
| `GATEWAY_DEFAULT_MODEL` | Override the concrete default route |
| `GATEWAY_APP_API_KEY` / `M87_GATEWAY_APP_API_KEY` | Replace the first configured app key |
| `GATEWAY_APP_ID` / `M87_GATEWAY_APP_ID` | Override that app's ID |
| `GATEWAY_ALLOWED_MODELS` | Comma-separated allowlist; an empty value clears access |
| `GATEWAY_APP_CAPTURE_CONTENT` | Legacy compatibility field; does not control logging |
| `GATEWAY_CAPTURE_CONTENT` | Gateway-wide content-capture switch for all authenticated applications |
| `GATEWAY_CONTROL_PLANE_ENABLED` | Enable the local SQLite store, admin API, and console |
| `GATEWAY_CONTROL_PLANE_DATABASE_PATH` | Local SQLite event and key-metadata path |
| `GATEWAY_CONTROL_PLANE_MASTER_KEY_PATH` | Owner-only provider-key encryption key path |
| `GATEWAY_BACKEND_ADAPTER` | Registered backend identifier; only `sqlite` is bundled |
| `GATEWAY_USAGE_RETENTION_DAYS` | Independent usage retention; default 365 days |
| `GATEWAY_CONTROL_PLANE_RETENTION_DAYS` | SQLite event retention in days; pruned at startup and on event writes |
| `GATEWAY_ADMIN_API_KEY` | Default environment source for the local admin key |
| `GATEWAY_CACHE_ENABLED`, `GATEWAY_CACHE_TTL_SECONDS`, `GATEWAY_CACHE_MAX_ENTRIES` | Cache enablement, expiry, and capacity |
| `GATEWAY_PROVIDER_MAX_ATTEMPTS`, `GATEWAY_PROVIDER_RETRY_BACKOFF_MS` | Maximum attempts and initial retry delay |
| `OPENAI_API_KEY` | Default OpenAI credential variable |
| `OLLAMA_BASE_URL` | Default Ollama endpoint override |

For app overrides, `apps` takes precedence when non-empty; otherwise the first
`auth.api_keys` entry is used. Both `key` and `api_key` spellings are supported
and old keys are removed during replacement. Use one app collection where practical.
All app identities and keys must be unique across both collections.

## Models and routing

Identifiers use `openai:model` or `ollama:model`. An app must allow both
`auto` and the selected concrete target. Unknown providers and malformed model
names are rejected. Models are not checked against a live provider catalog.

Direct concrete requests route to that model. For `auto`, the first matching
rule wins; otherwise `routing.default_model` is used. Rules can match
`when_model: auto`, `when_task`, or both. Targets accept `route_to` or the
legacy `model` spelling. Final-target authorization always applies.

## Providers

Applications can include `project_id` (default `default`). The control plane adds
configured projects at startup; its Projects page creates groups for runtime keys.
Project identifiers follow the same letters/digits/underscore/dot/hyphen convention
as app IDs. Membership affects event attribution and dashboards, not model policies
or operator authorization. See [project operations](runbooks/projects-and-usage.md).

Each provider accepts `enabled`, `base_url`, `base_url_env`, `api_key_env`,
and `timeout_seconds`. Endpoints from the configured environment variable take
precedence over YAML and are validated at startup. HTTP(S) endpoints cannot
contain embedded credentials, queries, or fragments.

OpenAI defaults to `https://api.openai.com/v1`. It first uses the encrypted
`default` key from the enabled local control plane, then its configured environment
variable. Ollama defaults to `http://localhost:11434` and calls
`/api/chat`. A disabled provider is rejected before invocation. Missing OpenAI
credentials return a safe 503 when that provider is selected.

`providers.openai_compatible` supports the current non-streaming text contract at
an explicitly configured base URL, typically ending in `/v1`. Its key is optional;
Ollama can also use a gateway-stored or environment bearer key for protected endpoints.
Registered source extensions use `providers.custom.<adapter-name>`; see
[adapters](adapters.md). Model discovery is an operator check, not an enforcement
catalog: model authorization still uses each app's allowlist.

The normal `m87-gateway` launcher starts with its own private defaults rather than
loading YAML/demo configuration. The existing Uvicorn entry point retains YAML
and environment loading. With the control plane enabled, saved UI connections,
default model, and capture setting override corresponding startup values on
restart. Endpoint changes require new credentials or explicit removal if a key
was previously configured. See [guided setup](runbooks/guided-setup.md).

## Policy and observability

| Setting | Behavior |
| --- | --- |
| `guardrails.blocklist.enabled` / `blocked_terms` | Case-insensitive configured request checks; matched terms are not echoed |
| `guardrails.max_message_chars` | Per-message character bound; default 65,536 |
| `guardrails.max_request_bytes` | Body limit before JSON parsing, including chunked bodies; default 262,144 bytes |
| `observability.json_logs` | JSON metadata outcome events on stdout |
| `observability.prometheus_metrics` | Metrics recording and `/metrics` endpoint |
| `observability.traffic_log` | Optional private rotating JSONL storage and bounded content capture |
| `control_plane.enabled` | Optional local SQLite event/key store, admin API, and `/admin` console |
| `control_plane.database_path`, `master_key_path` | Private local persistence paths |
| `control_plane.admin_api_key_env` | Environment variable containing the admin key |
| `control_plane.backend_adapter` | Bootstrap backend selection; default `sqlite` |
| `control_plane.usage_retention_days` | Bootstrap usage retention; default 365 days |
| `control_plane.retention_days` | SQLite event-pruning window; default 30 days |
| `apps[].capture_content` / `auth.api_keys[].capture_content` | Legacy compatibility fields; ignored by gateway-wide capture |
| `rate_limit_per_minute` | Enforced rolling 60-second request allowance per app and process |
| `monthly_budget_usd` | Validated future budget field; not enforced |
| `cache.enabled`, `ttl_seconds`, `max_entries` | Opt-in in-memory response cache |
| `retry.max_attempts`, `backoff_ms` | Bounded transient provider retries; default one attempt |

The text-chat contract accepts messages, model, temperature, max_tokens, optional
task, and `stream: false`. Streaming, tools, images, arbitrary extra options,
and tool-role messages are rejected with a safe 422.

See [observability](observability.md) for content storage and retention,
[configuration changes](runbooks/configuration-changes.md) for rotation, and
[Worker integration](integrations/worker-local-inference.md) for the reference use case.

## Persistent console controls

Use **Controls** to edit gateway concurrency, request bytes/message characters,
retry attempts/backoff, cache enablement/TTL/capacity, SQLite retention days, and
capture character limits. Set the per-provider timeout in **Setup**, gateway-wide
content capture in **Setup**, and managed application rate/concurrency limits in
**Applications**. A blank application limit inherits the gateway concurrency cap
or disables its rate allowance. Existing keys remain valid.

Updates apply to new requests and persist in the private SQLite runtime
configuration. Saving setup, connections, or controls clears response caching;
in-flight requests keep their original settings. Active concurrency counts and
rate windows are preserved on edits, but reset at process restart. Lowering a
concurrency cap does not cancel admitted work. Admission rejects excess work with
429 and `Retry-After: 1`, without queueing.

YAML supports `limits.max_concurrent_requests` (default 64) and application
`max_concurrent_requests` (default null). These are single-process limits.
SQLite retention is applied at startup, on Controls save, and on event writes.
Idle instances do not run a background expiry timer. Shortening retention removes
older traffic records. Usage has its own retention and survives traffic deletion. It does not manage separate JSONL
files. See [acceptance runbook](runbooks/gateway-controls-testing.md).

Backend repository contracts and trusted source extensions are documented in
[backend adapters](backend-adapters.md). Existing stores migrate to schema 2 on
startup; follow [backend acceptance](runbooks/backend-storage-testing.md) before upgrade.
