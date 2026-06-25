# M87 AI Gateway

Secure, observable, provider-neutral AI gateway for production apps.

> Early-stage open-source project. Built in public by M87 Tech Labs.

## Why this exists

Most AI apps start by calling LLM providers directly from a frontend or application backend. That works for demos, but production systems need a controlled service layer for authentication, authorization, model routing, guardrails, logging, observability, and cost visibility.

M87 AI Gateway provides a lightweight, self-hostable AI gateway that apps can call instead of calling providers directly.

```text
Frontend / App / Worker / Backend
        |
        | HTTPS + API key / JWT
        v
M87 AI Gateway
        |
        | AuthN/AuthZ, routing, guardrails, logs, metrics
        v
OpenAI / Anthropic / Ollama / Bedrock / other providers
```

## Current status

This repository is in early development. The first public milestone is `v0.1.0`.

## Planned v0.1.0 features

- OpenAI-compatible `/v1/chat/completions` endpoint
- API key authentication
- OpenAI provider
- Ollama provider
- Rule-based model routing
- Basic guardrail blocklist
- Structured JSON logs
- Docker Compose quickstart
- Prometheus `/metrics` endpoint foundation

## Quickstart

Copy the environment file:

```bash
cp .env.example .env
```

Edit `.env` and set at least one provider key, or run with Ollama locally.

Start the gateway:

```bash
docker compose up --build
```

Call the gateway:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer demo-app-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "Explain AWS VPC in simple terms"}
    ]
  }'
```

## Repo structure

```text
src/m87_gateway/        Gateway source code
docs/                   Project documentation
examples/               Sample integrations
deploy/                 Deployment assets
tests/                  Automated tests
.github/                GitHub workflows and templates
```

## Versioning

This project uses Semantic Versioning.

- `v0.x.x`: early development; breaking changes may occur
- `v1.0.0`: stable public API and configuration contract

## License

Apache License 2.0.
