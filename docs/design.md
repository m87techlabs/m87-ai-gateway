# Product design

## Purpose and audience

M87 AI Gateway is a self-hostable gateway framework for developers and small
organizations that need a consistent way to call language models. Applications
should integrate once, while operators control credentials, model access,
provider selection, policy checks, and operational visibility.

The initial product is a deployable HTTP service. Its framework capabilities are
documented adapter and policy interfaces, reusable configuration, and deployment
examples. A separately supported embedded SDK is a future decision.

## Product principles

1. Make the first successful local request straightforward and reproducible.
2. Enforce application identity and model authorization before spending provider resources.
3. Define a small, explicit API compatibility contract and test it across providers.
4. Keep provider credentials on the server and sensitive content out of default logs.
5. Make failures understandable through stable errors and correlated operational signals.
6. Keep the default service lightweight; add infrastructure when a demonstrated need requires it.
7. Publish only the capabilities that a release actually supports.

## Core scope

| Capability | Product expectation | Current state |
| --- | --- | --- |
| API | Documented chat completion contract; explicit handling of unsupported options | Partial: text requests and non-streaming responses |
| Identity | Per-app authentication and model authorization, including resolved routes | Implemented for bearer app keys and model allowlists |
| Routing | Deterministic selection, aliases, configuration validation | Implemented for direct models, `auto`, and task rules |
| Providers | Common adapter contract with declared capabilities and safe failure handling | Partial: non-streaming OpenAI and Ollama text chat; native Ollama flow verified |
| Policy | Configurable request/response checks with bounded request sizes | Partial: request bounds and configured blocklist; response checks planned |
| Reliability | Timeouts, cancellation, bounded retries, explicit fallback policy | Partial: HTTP timeouts only |
| Observability | Request IDs, outcome logs, latency, usage, cost estimates, metrics | Partial: correlated events, metrics, and optional local traffic capture; cost/export planned |
| Resource controls | Per-app rate limits and documented budget semantics | Planned: fields exist but are unenforced |
| Operations | Local and container setup, health/readiness, upgrade and rollback procedures | Partial: health endpoint, Docker files, and runbooks |

## Target request path

This diagram describes the intended design. See [architecture](architecture.md)
for the current implementation.

```mermaid
flowchart TD
    Client[Application] --> API[Validate request and assign request ID]
    API --> Auth[Authenticate application]
    Auth --> Route[Resolve model and authorize final target]
    Route --> Limits[Check limits and request policy]
    Limits --> Adapter[Select enabled provider adapter]
    Adapter --> Provider[Call model service]
    Provider --> Response[Normalize response and apply response policy]
    Response --> Client
    API -.-> Observe[Safe logs, metrics, and usage]
    Limits -.-> Observe
    Adapter -.-> Observe
    Response -.-> Observe
```

## Provider access and cloud hosting

Provider integration and deployment are separate commitments:

- **Provider integration:** call model services offered by OpenAI, Ollama,
  Anthropic, AWS Bedrock, Azure OpenAI, and Google Cloud Vertex AI.
- **Cloud hosting:** run the gateway on AWS, Azure, and Google Cloud using the
  same container and documented platform configuration.

All three major cloud integrations are planned. The initial runtime does not
implement their adapters, credential handling, or deployment automation.
Provider-specific capabilities must be declared explicitly; compatibility does
not imply every model offers the same features.

```mermaid
flowchart LR
    App[Client application] --> Gateway[Gateway service]
    Gateway --> Contract[Provider adapter contract]
    Contract --> Direct[OpenAI and Anthropic]
    Contract --> Local[Ollama]
    Contract --> AWS[AWS Bedrock]
    Contract --> Azure[Azure OpenAI]
    Contract --> GCP[Google Cloud Vertex AI]
```

## Extension contract

Before treating adapters as a public extension API, define and test:

- Provider identity, supported model identifiers, configuration, and credential sources.
- Supported request fields, response shape, streaming, tools, and multimodal capabilities.
- Safe errors for unsupported features, invalid configuration, throttling, and outages.
- Timeout, cancellation, connection reuse, retry, and usage-reporting behavior.
- Contract tests, a configuration example, and a troubleshooting runbook.

Providers must not own application authorization or silently bypass policy.
Normalize the common subset and document provider-specific options. Never invent
usage data when a provider does not supply it.

## Reliability and isolation decisions

- Resolve a route before final authorization. Every fallback target also needs authorization.
- Validate configuration at startup and fail closed on invalid identity or policy settings.
- Treat retries as potentially billable duplicate work; retry only under a documented policy.
- Do not retry a stream after response bytes have reached the client.
- Keep application credentials, provider credentials, and operator access separate.
- Establish single-instance limit semantics before promising limits across replicas.
- Report estimated costs separately from provider billing; pricing requires a maintained source.

Final-target authorization and startup validation are enforced. Retries, fallback,
shared limits, and maintained cost estimation remain acceptance requirements.

## Deployment assumptions

The first supported deployment is one gateway instance behind a trusted network
boundary or TLS reverse proxy. Applications call it from their backend. Operators
supply model access, credentials, connectivity, and model availability.

The default runtime should remain stateless where possible. Shared rate limiting,
durable usage accounting, and multi-replica coordination need explicit storage
decisions before implementation. SQLite, PostgreSQL, or a shared cache are options,
not current runtime requirements.

## Scope boundaries

The initial releases do not include a model training platform, model registry,
RAG orchestration system, billing platform, hosted control plane, or administrative
UI. New features need a demonstrated gateway use case and a place in the roadmap.

## Decision records

Record substantial choices in short documents under `docs/decisions/` when needed.
Include context, the decision, alternatives, consequences, and acceptance checks.
Update this page when a decision changes the product contract.
