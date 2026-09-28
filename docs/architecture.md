# Architecture

## Current request flow

The service uses FastAPI, a cached Pydantic configuration model, and HTTPX provider
adapters. The following sequence reflects the current source, including limitations.

```mermaid
sequenceDiagram
    participant App as Client application
    participant API as FastAPI route
    participant Auth as API-key dependency
    participant Config as Cached settings
    participant Guard as Hardcoded blocklist
    participant Route as Model selector
    participant Provider as Provider adapter
    App->>API: POST /v1/chat/completions
    API->>Auth: Bearer header
    Auth->>Config: Look up app key
    Config-->>Auth: App configuration or no match
    alt Authentication fails
        Auth-->>App: HTTP 401
    else Authenticated
        API->>Guard: Check message text
        alt Blocklist matches
            Guard-->>API: Block with matched term
            API-->>App: HTTP 400
        else Allowed
            API->>Route: Requested model and app allowlist
            Route-->>API: Direct model or configured default
            Note over API,Route: Disallowed requested models return 403
            API->>Provider: Chat request
            Provider-->>API: Normalized or upstream JSON
            API-->>App: Chat completion response
        end
    end
```

Provider exceptions are not normalized today. The route logs selected events,
but there is no complete outcome audit trail, request ID middleware, or metrics
endpoint. The current `auto` path does not check the resolved model against the
allowlist. The target flow in [design](design.md) addresses these gaps.

## Component boundaries

| Component | Source | Responsibility |
| --- | --- | --- |
| Application | `src/m87_gateway/main.py` | App construction and health route |
| API | `src/m87_gateway/api/` | Chat request/response schemas and orchestration |
| Configuration | `src/m87_gateway/config/` | YAML loading, environment overrides, cached settings |
| Authentication | `src/m87_gateway/auth/` | App bearer-key lookup |
| Routing | `src/m87_gateway/routing/` | Requested-model allowlist and default resolution |
| Guardrails | `src/m87_gateway/guardrails/` | Hardcoded request blocklist |
| Providers | `src/m87_gateway/providers/` | Adapter interface, factory, OpenAI/Ollama HTTP calls |
| Audit | `src/m87_gateway/logging/` | Selected events with top-level key redaction |
| Metrics | `src/m87_gateway/metrics/` | Placeholder |

## Process and deployment boundaries

Configuration is cached in memory. Each provider call currently creates its own
HTTP client. There is no database, background worker, shared limiter, or control
plane. The Docker image runs one Uvicorn process.

See [stack](stack.md) for technologies, [design](design.md) for the intended
architecture, and [runbooks](runbooks/README.md) for operational procedures.
