# Validation status and deferred checks

## Working policy

Docker is enabled on demand in the development environment to conserve resources.
Documentation, lint, unit tests, and Python package builds run without it. Leave
Docker stopped during work that does not need a container runtime.

Before a container check is needed, state the specific checks and prerequisites
so the operator can enable Docker integration for WSL. Run the bounded check set,
stop the project's containers afterward, and record the results here. The operator
controls when to stop Docker Desktop itself.

## Independent chat sample

Checked on 2026-10-02 in Linux/WSL: 123 Python tests and nine browser DOM interaction
tests passed. The new sample's checks cover server-held application credentials,
conversation forwarding, reported/unknown usage, safe authentication/authorization/
rate-limit errors, connection failures, timeouts, invalid conversations, cross-origin
rejection, text-safe browser rendering, follow-up history, failed-turn retry, and
duplicate-send prevention. Ruff, ShellCheck, Bash/JavaScript syntax, 44-file
documentation checks, and whitespace checks passed.

A real HTTP test started the sample with its shell launcher, a temporary gateway,
and a synthetic inference server. A question returned six reported tokens and a
request ID matching the gateway's captured input/output under the sample project.
Temporary processes were stopped and existing user configuration was untouched.
This is an HTTP integration check with synthetic inference, not a live-model check.
Live Ollama/cloud inference through this sample and visual review in a real browser
remain operator checks; DOM tests do not establish visual rendering. Docker was
unnecessary. See the [sample procedure](../examples/chat_app/README.md).

## Local lifecycle scripts

Checked on 2026-10-02 in Linux/WSL: the full Python suite passed 111 tests,
including six lifecycle checks. Real temporary gateway processes verified source
start, health, duplicate-start protection, status, graceful stop, idempotent stop,
restart preserving the operator key/database, occupied-port isolation, stale PID
protection, unsafe runtime-file rejection, and standalone executable fallback.
Every test used isolated private data and cleaned up its managed gateway.
ShellCheck, Bash syntax, Ruff lint/format, 43-file documentation checks, and
`git diff --check` passed. Hosted CI checks Bash syntax and exercises the lifecycle
scripts against both source and a freshly built Linux executable.

No model inference or Docker startup was needed for this change. Native Windows
lifecycle scripts, OS service installation, and automatic startup after reboot
remain unverified/unimplemented. The Linux scripts manage their own background
process; existing manually launched servers and inference services keep their
separate lifecycle. Follow [guided setup](runbooks/guided-setup.md).

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

The native model path is now verified in the flow-lab session below. Docker Desktop
WSL integration is needed separately for Phase 3 container checks. After Phase 3
passes, enable the dedicated Tunnel and Worker test route for Phases 4 through 6.
Do not reuse an established application route for the first remote test.

### Docker-free Windows/WSL flow lab

The local flow application was checked on 2026-10-01 and 2026-10-02 with Python
3.12. The launcher started a WSL relay on loopback port 8787 and a WSL gateway on
loopback port 8080. The gateway reached Windows Ollama on port 11434 without Docker.

| Check | Result | Sanitized evidence |
| --- | --- | --- |
| Relay unit tests | Passed | 6 tests for dependency preflight, key isolation, request forwarding, correlation, safe failures, and size limits |
| Windows-to-WSL forwarding | Passed | Windows HTTP client reached the page and status route through `localhost:8787` |
| Page and static assets | Passed | HTML, JavaScript, and CSS returned HTTP 200 |
| Browser security headers | Passed | Same-origin CSP, no-store, frame denial, and content-type protection |
| Gateway status through relay | Passed | HTTP 200; gateway reported reachable |
| Ephemeral app authentication | Passed | Gateway identified `local-flow-lab`; key was absent from browser responses |
| Ollama provider attempt | Passed | `auto` resolved to the selected Ollama route and reached the Windows service |
| Missing-model behavior | Passed | Browser received a safe HTTP 502 and gateway-generated request ID |
| Correlation and privacy | Passed | Browser ID matched metadata; synthetic marker was absent from response metadata and event output |
| Coordinated cleanup | Passed | One Ctrl+C stopped relay and gateway cleanly |
| Successful completion | Passed | `auto` resolved to `ollama:gemma3:1b`; HTTP 200; 33 prompt and 26 completion tokens |

This session verifies the application, relay, gateway, and Windows provider
boundary for both the expected model-missing error and a real completion. The
successful request ID matched the metadata event, and synthetic prompt content
remained absent from metadata and metrics. Docker remains required only for the
separate image and Compose acceptance phase.

## Local control-plane implementation

The developer-preview control plane was checked locally on 2026-10-02 with
Python 3.12.

| Check | Result | Evidence |
| --- | --- | --- |
| Focused configuration, store, and ASGI integration | Passed | 10 tests covering environment switches, usage/content events, app-key hashing/revocation, provider-key encryption, admin auth, and console APIs |
| Credential plaintext checks | Passed | Generated app and provider keys were absent from SQLite bytes; provider secrets were absent from list responses |
| Private storage permissions | Passed | Database, SQLite sidecars, and master key use owner-only permissions |
| Package build | Passed | Wheel built; HTML, CSS, and JavaScript console assets were present |
| Static checks | Passed | Ruff lint/format, Python compilation, JavaScript syntax, Markdown links/fences, YAML parsing, and whitespace |
| Hosted full suite and package | Passed | 88 tests, Ruff, wheel build, docs, and Worker example for commit `5a62105`; [CI run](https://github.com/m87techlabs/m87-ai-gateway/actions/runs/37023101314) |
| Full local pytest suite | Runner limitation | The current isolated WSL command runner stalls in AnyIO blocking portals and thread workers, including a minimal empty FastAPI application; tests using TestClient could not complete in this runner |
| Live Ollama control-plane flow | Deferred in this batch | Windows Ollama was not reachable from the isolated command runner; the earlier native completion remains recorded above |

The control-plane integration test uses HTTPX ASGI transport and a synthetic
provider. It verifies a dynamically generated application key can authorize a
chat and that the matching admin event contains provider-reported tokens and
opted-in request/response content. Hosted CI remains the full-suite gate.

## Deferred checks

### Projects, dashboard, and ecosystem vision

Checked on 2026-10-02 with Python 3.12 and Node 24 on Linux/WSL:

- Full Python suite: 105 passed, including project creation/membership,
  preservation of historical attribution on app movement, migration of old keys
  and events, YAML project discovery, caller-header isolation, scoped usage/log
  exports, cache accounting, nullable usage, time windows, restart persistence,
  and stable public project IDs while payload credentials remain redacted.
- Console DOM interaction tests: six passed for project selection/scoped requests,
  charts, project/app creation, app movement, application-key API testing, and
  lock cleanup, including a late exchange response. CSS parsed successfully.
  Dependencies are isolated under `tests/console` with an npm lockfile.
- Linux executable and wheel rebuilt. Standalone process checks passed for setup,
  provider discovery/auth, persisted project/key membership across restart,
  completion, six reported tokens, scoped usage, and captured exchange output.
- Live bundled gateway → Windows Ollama `gemma3:1b` passed with 17 prompt and
  3 completion tokens. The event and selected project's overview agreed on
  20 tokens, with matching captured input/output. Temporary test processes/data
  were cleaned up.
- Ruff, JavaScript syntax, 43-file documentation checks, and whitespace checks
  passed. Hosted CI includes the console interaction and bundle smoke checks.

Headless browser installation failed because its download repeatedly timed out.
DOM checks do not establish visual rendering, keyboard accessibility, or browser
compatibility. Those checks remain unverified. Docker stayed disabled; no Grafana,
Prometheus, Loki/collector, or Vault containers were started. Container-engine
startup, managed service profiles, secret-store adapters, and remote exporters are
planned in [ecosystem design](ecosystem.md), with no service-runtime validation yet.

### Guided setup and adapter framework

Checked on 2026-10-02 with Python 3.12 on Linux/WSL:

- Full automated suite: 99 passed, including source adapter registration,
  environment endpoint resolution, compatible HTTP discovery/chat, optional auth,
  setup authorization, encrypted connection credentials, endpoint-change safety,
  request/token/content events, per-app rate enforcement, and restart persistence.
- Experimental Linux executable: built with PyInstaller 6.22.3; the bundle smoke
  procedure starts a real gateway process and synthetic inference HTTP server,
  verifies console/assets/auth/discovery, restarts, completes a request, and checks
  six provider-reported tokens plus captured output and encrypted credential storage.
- Live bundled gateway → Windows Ollama: `ollama:gemma3:1b` completed successfully
  after configuration through the setup APIs. Discovery, application-key auth,
  17 prompt plus 4 completion tokens, and matching captured input/output passed.
  The temporary gateway and test data were cleaned up. Browser interaction itself
  was not automated.
- Ruff lint/format, JavaScript syntax, 41-file Markdown links/fences, wheel build,
  editable installation, CLI help, and Worker example checks passed. Hosted CI
  also builds and smoke-tests the Linux executable. Docker remains deferred.
- Hosted Python 3.11 checks passed for implementation commit `16892a3`: full
  tests/lint/wheel, documentation/Worker checks, and Linux bundle build plus
  setup/restart/request smoke test. [CI evidence](https://github.com/m87techlabs/m87-ai-gateway/actions/runs/37040531997).

The bundled inference server is synthetic. This check does not establish live
vLLM/OpenAI compatibility, a clean workstation without Python, native Windows
support, Windows ACL protection, Linux distribution/architecture portability,
service installation, signed artifacts, upgrade/rollback, or cloud deployment.
These remain release checks. The live Ollama check covers the WSL gateway boundary;
it does not establish native Windows gateway support. See
[guided setup](runbooks/guided-setup.md).

Traffic controls were checked on 2026-10-02: the full local suite passed 95 tests
outside the isolated command runner, including cache TTL/isolation/eviction,
rate-window enforcement, retry exhaustion, non-retryable failures, and additive
SQLite migration preserving existing keys. Ruff, JavaScript syntax, 39-file
documentation checks, and a wheel build passed. Live-model cache/retry exercises
and distributed enforcement remain unverified; use the
[traffic-controls runbook](runbooks/traffic-controls.md) during the next local
provider session. Docker was not needed for these automated checks.

| Check | Why it is unverified | Needed to run | Procedure / expected evidence |
| --- | --- | --- | --- |
| Compose validation | Docker CLI integration is unavailable in the current WSL environment | Enable Docker Desktop integration for this WSL distribution; prepare ignored `.env` | `docker compose config --quiet` exits successfully |
| Image build and container startup | Docker runtime is unavailable | Working Docker engine and image/dependency download access | Build from the intended commit; container stays running |
| Container health and local port binding | Requires the running container | Start the Compose service | `/health` returns 200; published gateway port is bound to host loopback |
| Container environment/config mounts | Requires the running container | Prepared test configuration and app key | Valid auth succeeds, missing/invalid auth fails, intended default route is selected |
| Container-to-host Ollama connectivity | Native provider path passed; container path is unverified | Docker plus the reachable Ollama listener and installed model | `host.docker.internal` resolves; a synthetic chat returns the intended model |
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

- Budget enforcement, response policies, readiness, cost estimates, and
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
