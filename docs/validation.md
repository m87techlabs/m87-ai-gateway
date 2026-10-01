# Validation status and deferred checks

## Working policy

Docker is enabled on demand in the development environment to conserve resources.
Documentation, lint, unit tests, and Python package builds run without it. Leave
Docker stopped during work that does not need a container runtime.

Before a container check is needed, state the specific checks and prerequisites
so the operator can enable Docker integration for WSL. Run the bounded check set,
stop the project's containers afterward, and record the results here. The operator
controls when to stop Docker Desktop itself.

## Verified baseline

Baseline: commit `88e76a6`, checked on 2026-09-28.

| Check | Result | Environment / evidence |
| --- | --- | --- |
| Existing pytest suite | 8 passed | Local Python 3.12; provider calls mocked |
| Hosted test job | Passed | GitHub Actions, Python 3.11; lint, tests, wheel build |
| Hosted docs job | Passed | GitHub Actions, Python 3.11 |
| Ruff | Passed | Explicit project lint rules |
| Python wheel build | Passed | Local isolated environment and hosted CI |
| Markdown links and fences | Passed | 30 Markdown files in the baseline |
| Mermaid syntax | Passed | All 16 diagrams parsed; visual rendering not reviewed |
| YAML parsing | Passed | Repository YAML files parse as mappings; not Compose runtime validation |
| Whitespace check | Passed | `git diff --check` |

The local test run emitted a dependency deprecation warning from the TestClient
stack; it did not fail tests. Mocked provider checks and a successful wheel build
do not establish live provider behavior or successful container deployment.

## Current implementation validation

The next 0.1.x implementation batch was checked locally on 2026-09-30 with Python
3.12. The expanded suite passed 74 tests with mocked provider HTTP, and Ruff passed.
Three zero-dependency Worker relay tests, a clean wheel build, dependency checks,
33-file documentation validation, YAML parsing, and all 19 Mermaid diagrams also
passed. A native Uvicorn smoke check verified startup, health, metrics, safe 401
handling, and metadata-only rejection logging. The existing TestClient dependency
warning remains non-fatal. Hosted Python 3.11 test/package and documentation/Worker
jobs passed for implementation commit `7867838` on 2026-09-30.

## Worker-to-local flow session

The first execution of the
[end-to-end flow runbook](runbooks/end-to-end-flow-testing.md) started on
2026-09-30 against gateway commit `38e2977`. Documentation changes for the runbook
were uncommitted during the runtime checks and did not change gateway behavior.

| Phase / check | Result | Sanitized evidence |
| --- | --- | --- |
| Phase 0: Docker | Deferred | Docker CLI was present through Docker Desktop, but WSL integration was disabled |
| Phase 0: Ollama API | Partial | `GET /api/tags` succeeded and returned an empty model list |
| Phase 0: Tunnel | Deferred | No local `cloudflared` process was active; remote configuration was not inspected |
| Phase 1: Python baseline | Passed | 74 tests; project-scoped Ruff lint and format; compile check |
| Phase 1: documentation | Passed | Links and fences checked in 34 Markdown files |
| Phase 1: Worker relay | Passed | 3 Node tests |
| N1 health | Passed | HTTP 200 with healthy service response |
| N2 metrics | Passed | HTTP 200 with Prometheus text |
| N3 missing app key | Passed | HTTP 401; response and metadata request IDs matched |
| N4 invalid app key | Passed | HTTP 401 without credential disclosure |
| N5 successful Ollama chat | Deferred | No model was installed, so a successful completion could not run |
| N6 disallowed model | Passed | HTTP 403 before provider invocation |
| N7 blocklist | Passed | Safe HTTP 400 before provider invocation |
| N8 missing Ollama model | Passed | Safe HTTP 502; provider request and error counters increased once |
| Metadata privacy | Passed | Synthetic prompt markers were absent; events contained bounded metadata |
| Native cleanup | Passed | Uvicorn stopped cleanly after the test |

The native test verified gateway authentication, authorization, guardrails,
routing to Ollama, safe provider errors, request correlation, metadata logging,
and bounded metrics. It did not verify a successful completion or response-content
capture because Ollama had no installed model. Content-capture behavior remains
covered by automated tests.

The remaining native prerequisite is an installed test model. Docker Desktop WSL
integration is needed separately for Phase 3 container checks. After Phases 2 and
3 pass fully, enable the dedicated Tunnel and Worker test route for Phases 4
through 6. Do not reuse an established application route for the first remote test.

### Docker-free Windows/WSL flow lab

The local flow application was checked on 2026-10-01 with Python 3.12. The
launcher started a WSL relay on loopback port 8787 and a WSL gateway on loopback
port 8080. The gateway reached the Windows Ollama API on port 11434 without Docker.

| Check | Result | Sanitized evidence |
| --- | --- | --- |
| Relay unit tests | Passed | 5 tests for key isolation, request forwarding, correlation, safe failures, and size limits |
| Windows-to-WSL forwarding | Passed | Windows HTTP client reached the page and status route through `localhost:8787` |
| Page and static assets | Passed | HTML, JavaScript, and CSS returned HTTP 200 |
| Browser security headers | Passed | Same-origin CSP, no-store, frame denial, and content-type protection |
| Gateway status through relay | Passed | HTTP 200; gateway reported reachable |
| Ephemeral app authentication | Passed | Gateway identified `local-flow-lab`; key was absent from browser responses |
| Ollama provider attempt | Passed | `auto` resolved to the selected Ollama route and reached the Windows service |
| Missing-model behavior | Passed | Browser received a safe HTTP 502 and gateway-generated request ID |
| Correlation and privacy | Passed | Browser ID matched metadata; synthetic marker was absent from response metadata and event output |
| Coordinated cleanup | Passed | One Ctrl+C stopped relay and gateway cleanly |
| Successful completion | Deferred | Windows Ollama returned an empty installed-model list |

This session verifies the application, relay, gateway, and Windows provider
boundary through the expected model-missing response. Install a Windows Ollama
test model to complete the successful chat and response-content checks. Docker
remains required only for the separate image and Compose acceptance phase.

## Deferred checks

| Check | Why it is unverified | Needed to run | Procedure / expected evidence |
| --- | --- | --- | --- |
| Compose validation | Docker CLI integration is unavailable in the current WSL environment | Enable Docker Desktop integration for this WSL distribution; prepare ignored `.env` | `docker compose config --quiet` exits successfully |
| Image build and container startup | Docker runtime is unavailable | Working Docker engine and image/dependency download access | Build from the intended commit; container stays running |
| Container health and local port binding | Requires the running container | Start the Compose service | `/health` returns 200; published gateway port is bound to host loopback |
| Container environment/config mounts | Requires the running container | Prepared test configuration and app key | Valid auth succeeds, missing/invalid auth fails, intended default route is selected |
| Host Ollama connectivity | No live container/provider check performed | Docker plus a reachable Ollama listener and installed model | `host.docker.internal` resolves; a synthetic chat returns the intended model |
| OpenAI end-to-end response | No live provider check performed | Provider credentials, accessible model, and an intentional quota-consuming test session | Synthetic authenticated chat succeeds with the configured OpenAI route |
| Configuration restart and key rotation | Operational path not exercised | Running test instance and synthetic keys | New key works after recreation; retired key fails; safe rollback works |
| Deployment rollback | No container deployment validated yet | Working current and previous artifacts/configurations | Restore previous version and repeat health/auth/chat checks |

Follow [container deployment](runbooks/container-deployment.md),
[configuration changes](runbooks/configuration-changes.md), and
[provider troubleshooting](runbooks/provider-troubleshooting.md). A local Python
instance can exercise live provider behavior without Docker; container networking
and image checks still require Docker.

## Acceptance criteria still requiring implementation

Enabling Docker does not complete these roadmap items:

- Enforced rate limits/budgets, response policies, readiness, cost estimates, and
  durable/remote event delivery remain incomplete or absent.
- AWS Bedrock, Azure OpenAI, Google Cloud Vertex AI, and Anthropic adapters are
  planned; cloud contract/live checks depend on those adapters existing.
- Cloud deployment, persistence, and migration/restore validation need concrete
  implementations before operational support can be claimed.

These are feature acceptance gaps, distinct from checks deferred by the environment.
Track them in the [roadmap](roadmap.md).

## When to enable Docker

Enable it for changes to the Dockerfile, Compose, container networking, dependency
packaging that affects the image, or runtime behavior needing container verification.
It is also required before claiming the quickstart works or publishing a container
release. Batch related checks into one session. Documentation-only changes do not
require Docker unless they claim a newly verified container procedure.

## Recording a completed session

Record the date, commit, environment, exact checks, pass/fail results, limitations,
and sanitized evidence. Do not record secrets, real prompts, personal names, or
workstation paths. Keep the remaining deferred items explicit. Finish with
`docker compose down` for this project's test deployment to release its resources.
