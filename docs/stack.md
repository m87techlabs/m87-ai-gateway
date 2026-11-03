# Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | Keeps adapter development accessible |
| HTTP service | FastAPI and Uvicorn | Async API and streaming |
| Validation | Pydantic v2 | Request and configuration models |
| Provider HTTP | HTTPX | Async requests with bounded timeouts |
| Storage | SQLite in WAL mode | No external database for one instance |
| Credential encryption | `cryptography` Fernet | Encrypts stored keys with a separate master key |
| Metrics | Prometheus client | Per-process `/metrics` with bounded labels |
| Logging | JSON on standard output | Metadata only, for any log collector |
| Console | React, TypeScript, Vite, TanStack Query | Built into the image; no CDN assets, because of its content security policy |
| Packaging | Docker and Compose | One way to run on a laptop or a server |
| Images | amd64 and arm64 on GHCR | Covers Docker Desktop, Linux and Graviton |
| Monitoring | Prometheus, Grafana and Loki as a Compose profile | Optional, and off by default |
| Python tests | pytest, FastAPI TestClient, HTTPX MockTransport | Core and storage contracts |
| Console tests | Vitest, Testing Library, jsdom | Behaviour, with real-browser checks for releases |
| Lint | Ruff | Enforced in CI |
| Automation | GitHub Actions, Dependabot | Checks, publishing and updates, with pinned actions |

## Limits of this design

- One gateway per data volume. SQLite, rate limits and the cache are per process.
- Built-in adapters use OpenAI-compatible APIs. Other protocols need their own adapter.

## Considered for later

PostgreSQL and shared state for several instances, a secret store such as Vault, and OpenTelemetry
tracing. See the [backlog](backlog.md).
