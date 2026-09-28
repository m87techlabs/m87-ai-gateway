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

Later documentation-only commits use the same lightweight checks and hosted CI.
Update this baseline when runtime behavior changes or deferred checks are completed.

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

- Resolved-model authorization, configuration-driven guardrails/provider flags,
  and normalized provider errors need implementation and regression tests.
- Metrics, request IDs, complete outcome logs, enforced limits/budgets, and
  readiness behavior are incomplete or absent.
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
