# AGENTS.md: M87 AI Gateway

This is the project working guide. Follow it when changing this repository.

## What this is

A public, self-hosted AI gateway for developers building locally or using any LLM API. An app changes
only its base URL and key. Judge work by time to first request and by how little a calling app must
change. See [docs/roadmap.md](docs/roadmap.md), including what is deliberately **not planned**.

- **One way to run it:** Docker Compose, on a laptop or a server. Do not add installers, OS services or
  a console that controls Docker. Optional services are Compose profiles.
- **One place to control it:** the web console. New gateway features go in the list in
  `src/m87_gateway/control/features.py`, so they appear on the Features page.
- **Application is the unit of reporting:** its key sets `app_id` and `key_id` on the server side, and
  filters and metrics must keep working per application.

The official port is 8087. Keep the code brand-neutral where practical, because the product name may
change: package `m87_gateway`, CLI `m87-gateway`, image `m87-ai-gateway`.

## Repository

```text
src/m87_gateway/   Gateway, adapters and admin API
console/           Web console (React, TypeScript, Vite, TanStack Query)
tests/             Python tests; console tests live in console/src/test
docs/              Documentation; docs/runbooks holds procedures
deploy/            Monitoring configuration for the Compose profile
examples/          Sample app, Worker and log receiver
scripts/           Contributor tooling and checks
```

The console builds into `src/m87_gateway/control/static/`, which Git ignores. It loads nothing from a
CDN, because of its content security policy. Check console changes in a real browser, not only jsdom.

## API contract

- Forward fields the gateway does not model unless Strict mode is on. Bare upstream names such as
  `qwen3:14b` resolve through the default model's provider. Report the name the caller used.
- Built-in adapters use OpenAI-compatible APIs, including Ollama's `/v1`.
- Keep errors in the OpenAI shape with a `request_id`. Never fabricate token usage.
- See [docs/connect-your-app.md](docs/connect-your-app.md).

## Security rules

This project handles credentials and private prompts.

- Never log or return provider keys, application keys or the admin key.
- Never log provider response bodies; record only their HTTP status in `upstream_status`.
- Keep prompts and completions out of standard output and metrics. Capture is off by default, bounded
  and redacted, and exports carry metadata only unless explicitly chosen.
- Fail closed on authentication. Prefer allowlists.
- Never send stored credentials to a changed endpoint without explicit confirmation.
- Never commit real keys. `.env` stays ignored. Do not reintroduce implicit loading of the example config.
- Never store `user` raw or forward it; keep only its hash.

## Storage

SQLite is the default, through the repositories in `src/m87_gateway/control/repositories/`.

- Change schemas with additive migrations and bump `SCHEMA_VERSION`. An older gateway refuses a newer database.
- Keep existing keys and data. Migrate only isolated stores during development, and check for an
  existing store before starting a container on it.
- Keep usage records independent of log deletion and retention.
- Reuse `tests/backend_contracts.py` for new backends.

## Quality

- Every meaningful change has tests, and tests use temporary stores. Do not touch a running gateway.
- Keep docs current with behaviour. Every operator workflow needs a runbook linked from
  `docs/runbooks/README.md`.
- Distinguish implemented, partial, planned and verified. A parsed setting is not an enforced feature.
  Record what was and was not checked in `docs/validation.md`.
- Use honest maturity language. Avoid "enterprise-grade", "fully secure", or "production-ready" before 1.0.
- Use Mermaid where a flow is clearer as a diagram. Use type hints and small modules, and avoid speculative
  abstractions.

## Working in this repo

- Commit and push directly to `main` after local checks, then verify hosted CI. Do not open a pull request
  unless asked. Never force-push `main`.
- Use Conventional Commits and the generic repository-local identity. Do not add personal names, emails,
  workstation paths, credentials or tool attribution to repository content or commit metadata.
- Preserve published tags and history. History cleanup needs a separate, reviewed plan.
- Keep Docker independent of ordinary checks: docs, lint, unit tests and builds run without it. It is
  enabled on demand on a resource-limited machine, so run container checks together and stop what you
  started. Do not start optional services during routine development.
- Releases follow [docs/runbooks/release.md](docs/runbooks/release.md).

## M87 ecosystem knowledge: use Horizon

Documentation for every M87 Tech Labs repo (m87-playground, m87-ai-gateway,
homelab-docker, m87-infra, …) is indexed by **Horizon**, available to agents as
the `horizon` MCP server (`search_docs`, `get_document`, `list_sources`, `ask`).

- For context outside this repo — how other M87 apps do auth, secrets, CI or
  deployment; Cloudflare resources; homelab and infra setup; design decisions —
  search Horizon before reading other repositories, and cite the `repo/path`.
- Read files directly for this repo, for code and config (Horizon indexes
  Markdown), and for docs not yet pushed. Verify against code before editing.
- If Horizon is not available, say so and fall back to reading the repos.
- Keep this repo's docs current: Horizon answers from them.
