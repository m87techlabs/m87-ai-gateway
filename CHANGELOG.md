# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning and the Keep a Changelog format.

## [Unreleased]

### Added

- Schema-7 separate captured content, independent retention/read expiry and audited
  project content/log deletion preserving usage.
- Log search/paging, readable input/output, separate token counts, explicit capture
  states, recording-health counters and sample request-to-console links.
- Sixteen sample scenarios and packaged logging/backup recovery smoke.

- Schema-6 encrypted configuration history, validated rollback, ETag save/restore
  preconditions and transactional settings/connection/provider-key management audit.
- Configuration history and Storage health console pages, safe basic checks,
  explicit integrity/reversible write verification and missing-store protection.
- Current-credential preservation, confirmed changed-binding credential removal,
  15 sample acceptance scenarios and native revision/recovery smoke checks.

- Text SSE streaming for built-in providers, usage chunks, bounded parsing/capture,
  terminal errors, cache/retry bypass and full-lifecycle admission.
- Single-owner disconnect monitoring, upstream HTTP cancellation, final outcome
  metrics and schema-5 traffic fields preserving prior keys/usage/audit.
- Sample streaming/Stop UI, SDK/real TCP cleanup tests and native stream smoke.

- Authenticated model listing, adapter capability declarations/console matrix,
  bounded generation parameters and hashed gateway-only user attribution.
- Optional global/per-app bounded request queues, wait/overflow errors, cancellation
  cleanup, queue metrics/log fields and schema-4 preservation migration.
- SDK compatibility checks and sample model/parameter and queue recovery scenarios.

- Schema-3 application/key separation, overlapping key replacement, optional expiry,
  scoped revocation and transactional identity management audit in the console/API.
- Shared key-lifecycle adapter contracts and an isolated sample rotation scenario.

- Five SQLite repositories, trusted backend registration/configuration and shared
  adapter contracts; independent schema-2 usage records with atomic writes,
  duplicate-delivery protection, retention and migration preserving existing keys.

- Proposed backend architecture for embedded storage, secret/key lifecycle,
  configuration revisions, independent usage history and optional exporters.
- Explicit CI container packaging option while backend development takes priority.

- Setup Test connection probes draft endpoints without saving or generating completions,
  reports safe outcomes and protects stored credentials across endpoint changes.
- Explicit Docker image updates and documented native development/container checkpoints,
  separate persistence and encrypted migration guidance.

- Root Docker start/stop/status helpers with prerequisite checks, health waits,
  local source-build option and port/image-preserving resume.

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

### Changed

- Operator JSON exports omit captured content by default; include_content=true
  explicitly includes retained content. Repository compatibility exports remain unchanged.

## [0.1.0] - Historical scaffold

### Added
- Initial scaffold tag; the local MVP acceptance criteria were not complete.
