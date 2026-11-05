# Changelog

All notable changes to this project are documented here. It follows Semantic Versioning and the
Keep a Changelog format.

## [Unreleased]

### Added

- Single sign-on for the console through OpenID Connect, off until configured, with admin and read-only
  roles. Read-only people can see activity, settings and captured content, but cannot change anything.
  See the [runbook](docs/runbooks/single-sign-on.md).
- The audit log names the person, with a stable subject identifier, and records sign-ins, refused
  sign-ins, sign-outs and cache clears. Admin key actions appear as `admin-key`.
- Guidance for using an existing Prometheus and Grafana instead of the monitoring profile.
- The console's **Features** page shows one card for each job a gateway does, such as Authentication, Caching and
  Rate limiting, with its state and live numbers. Each opens its own page of settings, and shows what is planned.
- New documentation: [what the gateway does](docs/features.md) and
  [how data reaches Grafana](docs/grafana-data-flow.md).
- Alertmanager in the monitoring profile, with a guide to sending notifications. It sends nothing until
  you add a destination.
- Loki in the monitoring profile keeps 30 days and then deletes.

### Changed

- Store schema 12. Back up first, because an older gateway refuses a migrated store. Console sessions
  use a new format, so everyone signs in again.
- Session cookies are `Secure` behind a TLS proxy when `GATEWAY_PUBLIC_URL` is an HTTPS address.

### Fixed

- Bundled dashboards no longer name the monitoring profile's data sources, so they work in another Grafana.
- The HTTP 5xx and scrape availability panels keep a sensible axis when every value is zero.

## [0.1.2] - 2026-11-04

[Release notes](docs/releases/0.1.2.md)

### Added

- The console's sidebar shows the running version and commit, linked to its release notes.
- `GET /admin/api/about` returns the running version and commit.
- Release notes for each version under `docs/releases`, used as the GitHub release text.

### Fixed

- The console could return to a signed-in view just after a session expired.
- Readiness and startup messages named pages the console no longer has.

## [0.1.1] - 2026-11-03

[Release notes](docs/releases/0.1.1.md)

The first release: a drop-in OpenAI-compatible API with chat, streaming and embeddings; Ollama, OpenAI and
compatible adapters; per-application keys and reporting; a web console with a Features page; and Docker
Compose packaging with optional monitoring.

### Removed

- Portable Windows and Linux ZIPs, preview prereleases, native root start scripts and the native Grafana
  installer. Use Docker.

## [0.1.0] - Historical scaffold

### Added
- Initial scaffold tag; the local MVP acceptance criteria were not complete.
