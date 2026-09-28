# Configuration

The gateway loads YAML into Pydantic models and applies selected environment
overrides. Settings are cached for the process lifetime; restart after changes.

## File selection

The loader uses an explicit path when supplied by code. Otherwise it looks for:

1. `M87_GATEWAY_CONFIG`, then `GATEWAY_CONFIG`.
2. `config.yaml`, then `config.example.yaml` in the working directory.
3. An ancestor `config.example.yaml` relative to the configuration module.

A missing selected file currently falls back to empty settings instead of failing
startup. Always verify the selected file exists. Unknown configuration fields are
generally ignored; accepting a file does not establish that every setting is used.

For local customization, copy the example to ignored `config.yaml` and point
`M87_GATEWAY_CONFIG` at it. Compose mounts only `config.example.yaml` by default;
add a matching read-only mount if selecting another file inside the container.

## Environment variables

| Variable | Current effect |
| --- | --- |
| `M87_GATEWAY_CONFIG` / `GATEWAY_CONFIG` | Select YAML file |
| `GATEWAY_NAME`, `GATEWAY_ENVIRONMENT`, `GATEWAY_LOG_LEVEL` | Override parsed gateway metadata; not all metadata drives app/log setup |
| `SERVER_HOST`, `SERVER_PORT` | Override parsed settings; Uvicorn CLI arguments still control the actual listener |
| `GATEWAY_DEFAULT_MODEL` | Override the default route used by `auto` |
| `GATEWAY_APP_API_KEY` / `M87_GATEWAY_APP_API_KEY` | Override the first `auth.api_keys` entry's `key` |
| `GATEWAY_APP_ID` / `M87_GATEWAY_APP_ID` | Override the first `auth.api_keys` entry's app ID |
| `GATEWAY_ALLOWED_MODELS` | Comma-separated allowlist override for the first `auth.api_keys` entry |
| `OPENAI_API_KEY` | Read directly by the OpenAI adapter |
| `OLLAMA_BASE_URL` | Read directly by the Ollama adapter |

The loader does not read `.env` itself. Compose injects it; local Uvicorn needs
`--env-file .env` or an already configured process environment.

The example uses `auth.api_keys[].key`. The loader also accepts
`apps[].api_key`, but environment app-key overrides do not replace those entries.
An `auth.api_keys` entry using `api_key` instead of `key` can also retain its
old key due to alias precedence. Use the shipped spelling or edit such entries
directly until override behavior is corrected.

## Current enforcement

| Section | Implemented | Not yet enforced |
| --- | --- | --- |
| App identity | Key lookup and requested-model allowlist | Rate limits and monthly budgets |
| Routing | Concrete routes and `auto` default | Configured rules and final-target authorization |
| Guardrails | Hardcoded terms in source | YAML enable flag/terms, size limits, response checks |
| Providers | OpenAI/Ollama using fixed environment variable names | YAML enable flags, alternate credential variable names, custom OpenAI endpoint |
| Observability | Selected audit events | YAML toggles and Prometheus endpoint |
| Server | Parsed host/port values | Automatic Uvicorn listener configuration |

Keep provider secrets in environment/secret delivery systems. Example keys are
for demonstrations only. See [configuration changes](runbooks/configuration-changes.md)
for validation, rotation, verification, and rollback.
