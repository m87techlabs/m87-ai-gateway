# Configuration

The gateway loads YAML, applies selected environment overrides, and validates it
at startup. Unknown fields, malformed routes/endpoints, duplicate app IDs/keys,
and invalid limits fail startup. Settings are cached until the process restarts.

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
| `GATEWAY_APP_CAPTURE_CONTENT` | Enable or disable content capture for the first configured app |
| `GATEWAY_CAPTURE_CONTENT` | Global content-capture switch; still requires per-app permission |
| `GATEWAY_CONTROL_PLANE_ENABLED` | Enable the local SQLite store, admin API, and console |
| `GATEWAY_CONTROL_PLANE_DATABASE_PATH` | Local SQLite event and key-metadata path |
| `GATEWAY_CONTROL_PLANE_MASTER_KEY_PATH` | Owner-only provider-key encryption key path |
| `GATEWAY_CONTROL_PLANE_RETENTION_DAYS` | Event retention in days; pruned at startup |
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

Each provider accepts `enabled`, `base_url`, `base_url_env`, `api_key_env`,
and `timeout_seconds`. Endpoints from the configured environment variable take
precedence over YAML and are validated at startup. HTTP(S) endpoints cannot
contain embedded credentials, queries, or fragments.

OpenAI defaults to `https://api.openai.com/v1`. It first uses the encrypted
`default` key from the enabled local control plane, then its configured environment
variable. Ollama defaults to `http://localhost:11434` and calls
`/api/chat`. A disabled provider is rejected before invocation. Missing OpenAI
credentials return a safe 503 when that provider is selected.

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
| `control_plane.retention_days` | Startup event-pruning window; default 30 days |
| `apps[].capture_content` / `auth.api_keys[].capture_content` | Per-app permission, also requiring the global capture switch |
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
