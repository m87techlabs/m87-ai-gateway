# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning and the Keep a Changelog format.

## [Unreleased]

### Added

- Optional single-app Docker image and prebuilt Compose on localhost:8087,
  non-root runtime, persistent private storage and included provider setup UI.
- Real container smoke checks for run/Compose, host inference, tokens/content
  capture, credential persistence, recreation and graceful shutdown.
- CI-gated immutable/preview GHCR images and durable native preview release assets.
- Console redirect at the root URL and an option to hide operator keys from stdout.
- Native Windows/Linux portable preview artifacts and checksums, current-user Windows
  ACLs, instance locks/identity, native lifecycle commands and optional browser launch.
- Encrypted offline SQLite/key backups, fresh-directory restore, schema compatibility
  gates, native smoke checks and workstation upgrade/rollback guidance.
- Persistent console traffic/logging controls, editable application rate/concurrency
  limits, gateway admission caps, readiness diagnostics, scoped log deletion, and
  nine isolated sample HTTP failure/recovery scenarios.
- Single-process per-app rate limits, opt-in exact-response caching, bounded
  transient provider retries, console outcome fields, and traffic-control runbook.
- Initial public repository scaffold.
- Project documentation foundation.
- GitHub issue templates and CI workflow.
- Product design, roadmap, glossary, lifecycle, stack, and Mermaid diagrams.
- Runbooks for development, deployment, configuration, incidents, providers, and releases.
- Documentation checks, dependency updates, and repository hygiene defaults.
- Complete Apache 2.0 license text with the existing project copyright in NOTICE.
- Correlated JSON outcome events, optional bounded private traffic capture, and
  Prometheus request/provider/guardrail/token/log-sink metrics.
- A Worker-to-local-inference reference integration and traffic logging runbook.
- A Docker-free Windows/WSL browser flow application with an ephemeral gateway
  identity, coordinated launcher, and local testing runbook.
- An optional local control plane with SQLite event retention, request/token
  analytics, opted-in LLM input/output inspection, JSON export, and a packaged
  operator console.
- Runtime application-key creation/revocation and encrypted local OpenAI-key
  storage with separate operator authentication.
- Configuration, routing, policy, provider-failure, metrics, and logging tests.
- FastAPI gateway skeleton.

### Changed
- Adopted direct-to-main development with local checks and hosted CI verification.
- Documented deferred runtime checks and resource-conscious, on-demand Docker validation.
- Defined public gateway framework scope and major cloud provider targets.
- Replaced personal package contact metadata with a generic project identity.
- Documented actual implementation gaps and preserved the historical release tag.
- Bound development Compose access to loopback and added host-provider resolution.
- Made Python packaging explicit and expanded release/readiness guidance.
- Updated CI action pins and fixed the hosted runner to Ubuntu 24.04.
- Validate configuration at startup and reject unknown or malformed settings.
- Authorize resolved routes, apply configured request guardrails/provider flags,
  preserve Ollama chat semantics, and normalize provider failures.

### Fixed
- Close backup SQLite connections before removing temporary snapshots on Windows.

### Security

## [0.1.0] - Historical scaffold

### Added
- Initial scaffold tag; the local MVP acceptance criteria were not complete.
