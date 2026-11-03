# Changelog

All notable changes to this project are documented here. It follows Semantic Versioning and the
Keep a Changelog format.

## [Unreleased]

## [0.1.1] - 2026-11-03

The first release. Put M87 AI Gateway between your app and any LLM by changing only its base URL and key.

### Highlights

- **Drop-in OpenAI API:** chat completions, streaming and embeddings. Tools, images and vendor options are
  forwarded unchanged, and upstream model names like `qwen3:14b` just work.
- **Providers:** Ollama, OpenAI and any OpenAI-compatible server.
- **One application, one key:** per-app allowed models, limits, logs, usage and metrics, with key rotation.
- **Web console:** live dashboards, request logs with optional input and output capture, a streaming
  Playground, and a Features page to turn gateway features on and off.
- **Safe changes:** encrypted provider keys, configuration history with rollback, and encrypted backups.
- **Docker first:** one Compose file for amd64 and arm64, with optional Prometheus, Grafana and Loki.

### Get started

```bash
curl -fsSLO https://github.com/m87techlabs/m87-ai-gateway/releases/download/v0.1.1/docker-compose.yml
docker compose up -d
docker compose exec m87-ai-gateway cat /data/gateway/admin.key
```

Open http://localhost:8087 and sign in. See the
[README](https://github.com/m87techlabs/m87-ai-gateway#readme).

### Known limitations

- Early software: the API and configuration can change before 1.0.
- Verified live against Ollama. OpenAI and other compatible providers are implemented but not yet
  checked live, nor are tool calls through a real model, macOS, or a Linux host with a real model server.
- One instance per data volume. Limits and the cache are per process.
- Binds to `127.0.0.1` by default. **Not ready for direct internet exposure:** `/metrics` needs no key, and
  there is no built-in TLS. Put a TLS proxy with path rules in front. This is the focus of 0.2.
- Guardrails and capture read message text only, not tool arguments or images.
- Captured content is stored unencrypted, and capture is off by default.

See [what has been verified](https://github.com/m87techlabs/m87-ai-gateway/blob/main/docs/validation.md).

### Removed since the `v0.1.0` scaffold and earlier previews

- Portable Windows and Linux ZIPs, and preview prereleases. Use Docker.
- Native start scripts at the repository root. Contributors use `scripts/dev-*.sh`.
- The native Grafana installer. Use `docker compose --profile monitoring up -d`.

## [0.1.0] - Historical scaffold

### Added
- Initial scaffold tag; the local MVP acceptance criteria were not complete.
