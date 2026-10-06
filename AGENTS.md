# AGENTS.md — M87 AI Gateway

This file is the project working guide. Follow it when modifying this repository.

## Product direction and durable project context

Build a public, self-hostable gateway framework for developers and small organizations.
Treat it as a product with a documented core, tested provider interfaces, operational
runbooks, and explicit release gates. Public availability follows readiness; routine
development does not change repository visibility.

Product vision: make the gateway plug and play for workstation and cloud users.
The official local gateway port is 8087. Default workstation startup tries 8187,
8287, 8387, and subsequent increments of 100 if occupied, reports the selected URL,
and preserves unrelated services. Explicit port overrides remain exact. The sample
chat application uses an available port and separate start/stop/status scripts.
Ship one application with an included configuration UI and built-in operational
visibility. A user connects a supported inference endpoint or configures provider
credentials in the gateway, creates an application key, and points the calling
app at the gateway. Provider secrets remain gateway-side; app keys are separate.
Default local operation must not require Python, Docker, or external databases
once standalone distribution is implemented. Existing inference services and
cloud accounts remain user-supplied. Track this planned experience in design and
roadmap; do not claim packaging or provider support before verification.

End-product vision: a full AI gateway ecosystem with an included dashboard for
projects, applications, API testing, request/response logs, tokens, and usage.
The application should also offer optional managed service profiles for Grafana,
Prometheus, log storage/collection, Vault, and future integrations. After users
choose a profile, setup should configure dependencies, detect or start a supported
container engine when authorized, start the selected containers, report readiness,
and provide service links, lifecycle controls, retention, backup, and recovery.
Keep provider adapters, secret stores, log exporters, and service lifecycle adapters
extensible. The built-in workstation experience remains useful without Docker;
additional container profiles require a supported engine and explicit resource
choices. Container lifecycle management is planned until implemented and tested.
Do not start Docker or optional services during routine development; retain the
on-demand Docker policy below. Track this target in `docs/ecosystem.md` and roadmap.

Phase 1 controls are available in the included console: persistent cache/retry,
gateway concurrency, request/message bounds, SQLite retention and capture limits.
Managed application rate/concurrency limits can be edited without key replacement.
`/health` is liveness and `/ready` checks default-provider configuration/credentials
and local storage; it does not establish upstream connectivity. The chat sample's
isolated `python -m examples.chat_app.scenarios` suite exercises the HTTP flow and
failure/recovery without Docker or changes to a running gateway. Keep limits/cache
scoped to one process; budget/shared enforcement and remote delivery remain planned.

Backlog batch A2/A4/P2/R3 adds an authenticated model catalog, bounded generation
parameters, adapter capabilities in Setup, and optional process-local queueing.
Queueing defaults off; Controls persists depth/per-app/wait settings. Preserve
arrival provider/credential/cache snapshots while queued. Eligible FIFO, timeout,
queued disconnect/cancellation and metrics are implemented. Streaming and active
client-disconnect HTTP cancellation now have adapter and real TCP tests. Schema 4 adds nullable
queue/user-hash traffic fields while preserving keys/usage/audit. User attribution
is SHA-256 correlation only; never persist or forward the raw user field.

Streaming text is implemented for built-in adapters with cache/retry bypass,
first-chunk validation before headers, bounded SSE/NDJSON parsing, final usage or
unknown counts, terminal safe errors and bounded redacted capture. Sample chat
has a streaming toggle and Stop button; cancellation propagates through both
HTTP hops. Closing upstream HTTP does not guarantee backend compute/billing stops;
keep live provider evidence separate. Schema 5 preserves prior data while adding
outcome, wire-status, streaming and partial-content fields. A1 live verification
remains in backlog; A3 transport cancellation is implemented. Never fabricate usage.

Phase 2 portable preview uses native Windows/Linux builds, ZIPs and checksums,
OS-private storage, exclusive data-directory locks, and native status/stop commands.
Offline backups encrypt SQLite snapshots and local keys; restore accepts only fresh
private destinations. Schema versions reject newer databases before migration.
Document clean-host, Windows Ollama/browser, signing and cross-release rollback
checks separately; CI builders do not establish clean-workstation support.
Keep documentation synchronized with every implementation and validation change.

Root `docker-start.sh`, `docker-stop.sh` and `docker-status.sh` manage only the
fixed gateway Compose project, check Docker/Compose/engine requirements, and
preserve data on stop. Host Python is unnecessary. Default resume preserves the
existing image/port; --build, --update and --port are explicit startup overrides.
Current priority is backend architecture and native source development. Keep Docker
files/helpers available but defer further container work. Container build/publication
is an explicit CI workflow_dispatch package_container option; routine main pushes
run source/docs/native checks without rebuilding Docker. Packaging verification
remains required for the final functional release scope. Native and Docker
data stores remain separate. Draft connection tests use model discovery without
saving or completing inference; never send stored credentials to a changed endpoint.
Container distribution uses a non-root single-app image with the included setup
UI, port 8087 and private state in a named volume. Default Compose pulls a prebuilt
image; the source-build override remains available. Hide operator keys in container
stdout. CI must pass source, docs, native bundles and Docker run/Compose smoke before
publishing immutable commit/preview tags and durable commit prerelease downloads.
Keep private access unchanged until public release review. Container desktop/live
provider, backup/restore and distinct-version checks require separate evidence.

The core covers API compatibility, application authentication and authorization,
deterministic routing, provider adapters, policy checks, safe errors, observability,
and resource controls. AWS Bedrock, Azure OpenAI, and Google Cloud Vertex AI are
explicit provider targets. Hosting on AWS, Azure, and Google Cloud is a separate
deployment objective. Cloud capabilities remain planned until tested and documented.

The backend direction is documented in docs/backend-architecture.md:
SQLite stays the embedded default while services/repositories separate configuration,
identities, secret storage, traffic/content, usage and management audit. Six SQLite
repositories and an explicit trusted backend registry are implemented.
Schema 2 introduced independent usage; schema 3 separates application metadata
from multiple credential digests and adds transactional identity management audit.
Overlap, optional replacement expiry, individual revocation and a ten-active-key
bound are implemented. Actor is the shared operator role. Configuration/secret
audit, individual operator identity and master-key version migration remain planned.
Schema 2 separates content-free usage records from traffic; usage retention defaults
to 365 days, traffic to 30. Duplicate IDs preserve first usage attribution, and
traffic deletion leaves accounting intact. Upgrade backfills only retained events.
Shared tests in tests/backend_contracts.py must be reused by new adapters.
Remote stores/exporters remain optional and planned. Preserve current keys/data with explicit migrations; do not claim these
remaining planned features are implemented or silently move user data.

Use these pages as the lasting source of project context:

- `docs/README.md`: documentation navigation and status conventions.
- `docs/roadmap.md`: milestone scope, acceptance criteria, and provider coverage.
- `docs/design.md`: product boundaries, assumptions, and extension design.
- `docs/glossary.md`: shared terminology.
- `docs/lifecycle.md`: development, publication, compatibility, and retirement.
- `docs/stack.md`: technology choices and deployment targets.
- `docs/runbooks/`: repeatable procedures for implemented operational workflows.

Keep existing files and entry points. Update related docs and runbooks with behavior
changes. Use Mermaid diagrams where a flow, boundary, or lifecycle is easier to
understand visually. Distinguish implemented, partial, planned, and verified
capabilities; a parsed configuration field is not an enforced feature.

Use generic project identities and examples. Do not add personal names, personal
email addresses, workstation paths, credentials, or generated-tool attribution to
repository content or new commit metadata/messages. Configure identity locally to
this repository; do not change global Git identity. Preserve published history/tags;
historical identity cleanup requires a separate reviewed plan before public release.

Current workflow: commit and push directly to `main` after local checks, then verify
hosted CI. Do not open a pull request unless explicitly requested. Use Conventional
Commits and the generic repository-local identity. Fetch before pushing; preserve
remote work and never force-push `main`. Topic branches are optional temporary
workspaces, not a required review flow.

Docker in WSL is enabled only when needed because local resources are constrained.
Keep documentation, lint, unit tests, and package builds independent of Docker.
State the required container checks before asking the operator to enable it; batch
those checks and stop project containers afterward. Record verified and deferred
checks in `docs/validation.md`, including prerequisites and release implications.

Preserve the historical `v0.1.0` tag and choose a new version for the completed local MVP.
`docs/roadmap.md` and `docs/lifecycle.md` define current release gates; references
to the original v0.1.0 MVP below describe the baseline requirements to complete.

## Project identity

Repository: `m87-ai-gateway`

Current public name: **M87 AI Gateway**

Product name may change later. Keep the codebase brand-neutral where practical:

- Python package: `m87_gateway`
- CLI name, if added later: `m87-gateway`
- Docker image: `m87-ai-gateway`
- Config namespace: `gateway`
- Avoid hardcoding a future commercial product name in code.

## Project mission

Build a lightweight, self-hostable AI gateway for production applications.

Apps should call this gateway instead of calling LLM providers directly. The gateway should provide:

- Provider-neutral LLM access
- OpenAI-compatible API surface where possible
- Model routing and model selection
- App-level authentication and authorization
- Guardrails and request/response policy checks
- Structured audit logging
- Observability for Grafana, Prometheus, Splunk, and OpenTelemetry
- Cost and usage tracking
- Easy local, Docker, Kubernetes, and cloud deployment paths

## MVP target

The first milestone is `v0.1.0 — Local Gateway MVP`.

A developer should be able to clone the repo, run Docker Compose, and send a chat completion request through the gateway in less than 10 minutes.

Required `v0.1.0` behavior:

1. Client sends `POST /v1/chat/completions`.
2. Client authenticates with `Authorization: Bearer <app_api_key>`.
3. Gateway validates the app key.
4. Gateway validates the requested model or resolves `model: auto`.
5. Gateway runs basic guardrail checks.
6. Gateway routes the request to OpenAI or Ollama.
7. Gateway returns an OpenAI-compatible response.
8. Gateway writes structured JSON logs.
9. Gateway exposes health and metrics endpoints.

## Preferred tech stack

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic / pydantic-settings
- YAML config
- SQLite for local persistence later
- PostgreSQL for production persistence later
- Prometheus `/metrics`
- JSON stdout logging
- Docker and Docker Compose first
- Kubernetes/Helm later
- Terraform/ECS example later

Do not introduce heavy frameworks unless clearly justified.

## Current repository structure

Expected high-level structure:

```text
.
├── src/m87_gateway/
│   ├── main.py
│   ├── auth/
│   ├── config/
│   ├── guardrails/
│   ├── logging/
│   ├── metrics/
│   ├── providers/
│   └── routing/
├── tests/
├── docs/
├── examples/
├── deploy/
├── .github/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── config.example.yaml
├── .env.example
└── README.md
```

If folders do not exist yet, create them as needed while keeping the design simple.

## API design principles

### OpenAI-compatible endpoint

Primary endpoint:

```http
POST /v1/chat/completions
```

Expected request shape:

```json
{
  "model": "auto",
  "messages": [
    {"role": "user", "content": "Explain AWS VPC in simple terms"}
  ],
  "temperature": 0.7,
  "max_tokens": 500
}
```

Expected auth header:

```http
Authorization: Bearer demo-app-key
```

Return shape should be as close as practical to OpenAI chat completions:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "provider:model-name",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

If exact usage data is unavailable from a provider, return `null` or reasonable zero values and log that provider usage was unavailable. Do not fabricate token counts.

## Configuration design

Prefer YAML config with environment variable overrides.

Example config style:

```yaml
gateway:
  name: "M87 AI Gateway"
  environment: "local"
  default_model: "ollama:llama3.1"

server:
  host: "0.0.0.0"
  port: 8080

apps:
  - app_id: "demo-app"
    api_key: "demo-app-key"
    allowed_models:
      - "auto"
      - "openai:gpt-4o-mini"
      - "ollama:llama3.1"
    rate_limit_per_minute: 60
    monthly_budget_usd: 20

providers:
  openai:
    enabled: true
    api_key_env: "OPENAI_API_KEY"
  ollama:
    enabled: true
    base_url: "http://localhost:11434"

routing:
  default: "ollama:llama3.1"
  rules:
    - when_model: "auto"
      route_to: "ollama:llama3.1"

guardrails:
  enabled: true
  blocklist:
    - "ignore previous instructions"
    - "reveal your system prompt"

observability:
  json_logs: true
  prometheus_metrics: true
```

## Provider design

Use a common provider interface.

Suggested interface:

```python
class BaseProvider:
    provider_name: str

    async def chat_completion(self, request: ChatCompletionRequest, routed_model: str) -> ChatCompletionResponse:
        ...
```

Initial providers:

1. Ollama provider
2. OpenAI provider

Add Anthropic later.

Provider model names should use this convention:

```text
openai:gpt-4o-mini
ollama:llama3.1
anthropic:claude-3-5-sonnet
bedrock:anthropic.claude-3-5-sonnet
```

The string before `:` is the provider key.

## Routing design

Start with deterministic rule-based routing.

Initial behavior:

- If `model` is a concrete provider model, route directly after authz validation.
- If `model` is `auto`, use config `routing.default`.
- Later, add task-aware routing.

Do not build complex ML/LLM-based routing in v0.1.0.

## AuthN/AuthZ design

Start with app API keys.

Required checks:

- Missing `Authorization` header returns HTTP 401.
- Invalid API key returns HTTP 401.
- Valid app but disallowed model returns HTTP 403.
- Valid app and allowed model proceeds.

Never log raw API keys. If logging is needed, log only a short hash or last 4 characters.

Future auth methods:

- JWT validation
- OIDC/JWKS
- mTLS
- Signed requests

## Guardrails design

For v0.1.0, keep guardrails simple and explainable.

Initial checks:

- Prompt blocklist
- Optional response blocklist
- Max message length
- Max total request size

Guardrail result should be included in logs:

```json
{
  "guardrail_action": "allow|block|redact",
  "guardrail_reason": "blocklist_match|null"
}
```

If a request is blocked, return HTTP 400 or 403 with a safe message. Do not echo the blocked sensitive content back to the client.

## Logging design

Use structured JSON logs.

Every request should include:

```text
request_id
app_id
provider
model
routed_model
status_code
latency_ms
guardrail_action
guardrail_reason
prompt_tokens
completion_tokens
total_tokens
estimated_cost_usd
error_type
created_at
```

Never log:

- Raw provider API keys
- App API keys
- Full prompts by default
- Full completions by default
- Secrets or credentials

Prompt/response capture is implemented for complete and streaming text chat. The gateway-level
switch controls logging across all authorized apps; legacy app capture fields are
accepted for compatibility and ignored. It uses private SQLite or rotating JSONL
storage and remains best effort. Metadata stdout and metrics
must never contain message/completion text. Future remote exporters must consume
sanitized events asynchronously and define retention/access controls.

## Metrics design

Expose:

```http
GET /metrics
```

Use Prometheus-compatible metrics.

Suggested initial metrics:

```text
m87_gateway_requests_total
m87_gateway_request_latency_seconds
m87_gateway_provider_requests_total
m87_gateway_guardrail_blocks_total
m87_gateway_provider_errors_total
```

## Error handling

Use clear JSON errors:

```json
{
  "error": {
    "message": "Invalid API key",
    "type": "authentication_error",
    "code": "invalid_api_key"
  },
  "request_id": "..."
}
```

Do not leak provider exception internals to clients. Log internal details safely.

## Tests to maintain

Every meaningful feature should include tests.

Minimum tests for v0.1.0:

- Health endpoint returns 200.
- Missing auth returns 401.
- Invalid API key returns 401.
- Valid API key succeeds for allowed model.
- Disallowed model returns 403.
- Blocklisted prompt returns blocked response.
- `model: auto` resolves to configured default.
- Provider errors return safe gateway errors.

## Coding style

- Use type hints.
- Keep modules small.
- Prefer pure functions for routing/guardrail decisions.
- Avoid global mutable state unless FastAPI dependency injection makes sense.
- Keep public API behavior documented.
- Add docstrings for provider interfaces and non-obvious policy logic.
- Avoid speculative abstractions that are not needed for the next release.

## Commit convention

Use Conventional Commits:

```text
feat: add OpenAI-compatible chat endpoint
fix: handle missing authorization header
docs: add local quickstart
chore: add docker compose
test: add auth middleware tests
refactor: extract provider interface
security: redact API key from logs
```

## Branch strategy

Use simple branches:

```text
main
feature/<short-name>
fix/<short-name>
docs/<short-name>
```

Examples:

```text
feature/config-loader
feature/ollama-provider
feature/prometheus-metrics
fix/auth-header-validation
docs/quickstart
```

## Versioning and releases

Use Semantic Versioning:

```text
vMAJOR.MINOR.PATCH
```

Initial release plan:

```text
Next 0.1.x - Complete Local Gateway MVP (preserve historical v0.1.0 tag)
v0.2.0 - Observability Release
v0.3.0 - Security Foundation
v0.4.0 - Cloud-Native Deployment
v0.5.0 - Developer Experience
v1.0.0 - Stable Public API
```

Use annotated Git tags for releases:

```bash
# Example only: first verify this version is unused and all release gates pass.
git tag -a v0.1.1 -m "Release v0.1.1"
git push origin v0.1.1
```

## Implementation sequence

Work in this order:

1. Review the current scaffold and identify missing folders/modules.
2. Implement a real config loader from `config.example.yaml` and environment variables.
3. Add Pydantic models for chat completion requests and responses.
4. Implement API key auth and allowed-model authorization.
5. Implement model routing for concrete models and `auto`.
6. Implement a basic guardrail blocklist.
7. Implement Ollama provider with async HTTP calls.
8. Implement OpenAI provider using the official SDK or HTTP API.
9. Add structured JSON logging with request IDs.
10. Add Prometheus `/metrics`.
11. Add or update tests for each feature.
12. Update README quickstart once the flow works end-to-end.

## Definition of done for v0.1.0

The release is ready when:

- `pytest` passes locally.
- `docker compose up` starts the gateway.
- `/health` returns healthy.
- Auth works with `demo-app-key`.
- `model: auto` routes to the default model.
- Ollama provider works locally when Ollama is running.
- OpenAI provider works when `OPENAI_API_KEY` is set.
- Blocklisted prompts are blocked.
- JSON logs show request ID, app ID, model, provider, status, latency, and guardrail action.
- README has a working curl command.
- CHANGELOG has a `v0.1.0` entry or `Unreleased` section ready.

## Important non-goals for v0.1.0

Do not implement these yet unless explicitly requested:

- Admin dashboard
- Multi-tenant UI
- Billing system
- Complex policy engine
- LLM-based model router
- Full prompt/response storage
- Kubernetes operator
- Helm chart beyond placeholder docs
- Terraform production module beyond placeholder docs
- Enterprise SSO

## Security reminders

This is a security-adjacent gateway. Treat secrets carefully.

- Never commit real API keys.
- Keep `.env` ignored.
- Provide `.env.example` only.
- Do not log secrets.
- Do not log full prompts/responses by default.
- Redact authorization headers in logs and errors.
- Fail closed for auth errors.
- Prefer explicit allowlists over implicit access.

## Documentation standards

Every public feature should be documented in one of:

- `README.md`
- `docs/quickstart.md`
- `docs/configuration.md`
- `docs/security.md`
- `docs/observability.md`
- `docs/architecture.md`

Keep README focused on:

1. Problem statement
2. What the project does
3. Quickstart
4. Example request
5. Architecture diagram
6. Roadmap

Move deeper details to `docs/`.

## Tone and public positioning

Use professional, production-minded language.

Preferred positioning:

> M87 AI Gateway is a lightweight, self-hostable AI gateway for applications that need secure, observable, provider-neutral LLM access.

Avoid exaggerated claims like:

- “Enterprise-grade” before production maturity
- “Fully secure”
- “Best AI gateway”
- “Production-ready” before v1.0.0

Use honest maturity language:

- “Early-stage”
- “Developer preview”
- “Local MVP”
- “Built in public”
