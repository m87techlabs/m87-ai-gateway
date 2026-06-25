# Architecture

M87 AI Gateway is designed as a service layer between applications and LLM providers.

```text
Client App
   |
   | HTTPS + app auth
   v
Gateway API
   |
   +-- AuthN/AuthZ
   +-- Guardrails
   +-- Model Routing
   +-- Provider Adapter
   +-- Structured Logs
   +-- Metrics
   v
LLM Provider
```

## Major components

### API layer

Exposes OpenAI-compatible endpoints so existing applications can migrate with minimal changes.

### Auth layer

Authenticates calling applications and enforces model access policies.

### Routing layer

Selects the target model based on requested model, task hints, application policy, and future cost/latency rules.

### Guardrails layer

Applies configurable request and response safety checks.

### Provider layer

Abstracts individual providers such as OpenAI, Ollama, Anthropic, Bedrock, and others.

### Observability layer

Emits structured logs and metrics for dashboards, SIEM systems, and cloud logging services.
