# Roadmap

## v0.1.0 - Local Gateway MVP

- OpenAI-compatible `/v1/chat/completions` endpoint
- API key authentication
- OpenAI provider
- Ollama provider
- Rule-based model routing
- Basic guardrail blocklist
- Structured JSON logs
- Docker Compose
- README quickstart

## v0.2.0 - Observability Release

- Prometheus `/metrics`
- Request ID propagation
- Latency metrics
- Token usage metrics
- Provider error metrics
- Grafana dashboard example
- Splunk-friendly JSON logs

## v0.3.0 - Security Foundation

- JWT validation
- Per-app allowed models
- Rate limits
- PII redaction
- Prompt injection checks
- Audit log schema
- Expanded security documentation

## v0.4.0 - Cloud-Native Deployment

- Helm chart
- Kubernetes manifests
- Terraform ECS example
- Cloudflare Worker sample app
- PostgreSQL support

## v0.5.0 - Developer Experience

- Config validation CLI
- Health checks
- JavaScript and Python integration examples
- Provider fallback
- Better error messages

## v1.0.0 - Stable Public API

- Stable config schema
- Stable OpenAI-compatible endpoint behavior
- Documented provider interface
- Documented plugin interface
- Production deployment guide
- Security review checklist
