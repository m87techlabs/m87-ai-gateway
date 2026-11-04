# Changelog

All notable changes to this project are documented here. It follows Semantic Versioning and the
Keep a Changelog format.

## [Unreleased]

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
