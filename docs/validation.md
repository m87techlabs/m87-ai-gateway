# Validation status and deferred checks

## Working policy

Docker is enabled on demand in the development environment to conserve resources.
Documentation, lint, unit tests, and Python package builds run without it. Leave
Docker stopped during work that does not need a container runtime.

Before a container check is needed, state the specific checks and prerequisites
so the operator can enable Docker integration for WSL. Run the bounded check set,
stop the project's containers afterward, and record the results here. The operator
controls when to stop Docker Desktop itself.

## Configuration recovery and storage health

Verified on 2026-10-06 using private temporary stores: **300 Python tests**, **28
console interaction tests**, lint/format (97 Python files), wheel build and
links/fences in **54 Markdown files**. The isolated sample suite has **15 scenarios**.
A rebuilt Linux native preview passed setup, complete/streaming inference,
configuration restore, storage verification, lifecycle and encrypted backup/recovery,
including persisted revision history. No live user database was opened/migrated and
no user service or Docker container was started, stopped or rebuilt.

Schema 6 preserves existing identities, provider keys, traffic, independent usage and
management audit. Tests cover encrypted 100-entry history, baseline preservation,
restore of controls/default/capture, current-secret preservation, confirmed changed-
endpoint/all-alias removal, environment-binding safety, stale restore and ETag save
rejection, transactional rollback on audit failures, missing/corrupt snapshots,
operator-only APIs, safe key/file failures and real SQLite writer contention/recovery.
The reversible health probe leaves keys, usage and audit unchanged. SQLite operations
open existing files with `mode=rw`; missing running-store files are not recreated.
Browser checks cover safe history review, explicit confirmation/removal, stale
feedback, delayed responses after lock, ETag submission and explicit storage checks.
Shared backend contracts now include history and provider-key audit.

Manual visual browser/Windows Ollama checks, clean-host support, distinct-release
rollback, crypto key version rotation, remote adapters/exporters and final Docker
packaging remain deferred. Native CI builders do not establish clean-workstation
support. Audit actor remains shared operator; bootstrap/YAML changes and cache-clear/
log-deletion actions are outside this increment. See [recovery runbook](runbooks/configuration-recovery.md).

## Streaming and disconnect cancellation

Implemented text SSE for built-in adapters and upstream HTTP cancellation (A3)
for both response modes. Previous batch verified locally: 265 Python tests, 24 console interaction
tests, lint/format, wheel build and links/fences in 53 Markdown files. OpenAI Python
2.54.0 streamed real synthetic HTTP traffic through the gateway; no cloud calls
or stored credentials were used. The sample suite has thirteen isolated scenarios.

Tests cover all adapter streams, usage inclusion/unknown counts, byte-boundary
framing, safe initial/terminal errors, inactivity timeouts, missing DONE,
oversized events, changing stream identities, strict options, unsupported adapters,
cache/retry bypass and slot cleanup. Capture tests redact credentials split across
chunks, bound stored prefixes and flag truncation/partial failures. Real TCP tests
close clients directly and through the sample in both response modes, requiring
upstream closure, zero active/queued requests and one final cancellation record
within a bounded interval. Shared backend contracts preserve outcome metadata
across reopen; schema-3/4 upgrades preserve keys, usage and audit. Console tests
cover incremental safe text rendering, final usage, Stop and partial-history exclusion.
Native bundle smoke now exercises streaming and captured output.

Local Ollama discovery at loopback port 11434 timed out on 2026-10-06, so live
streaming inference was not attempted. A1 live evidence remains in the backlog:
Windows/Ollama, OpenAI/vLLM, backend generation-stop/billing behavior and Worker/
tunnel/proxy buffering checks. Transport cancellation does not prove those backend
behaviors. Visual browser review, clean-host packaging and final Docker verification
remain deferred. No live user database or running Docker instance was changed.
See [the streaming runbook](runbooks/streaming-and-cancellation.md).

## Inference API and request queueing

Backlog A2/A4/P2/R3 are implemented. Previous batch verification: 236 Python tests, 19
console interaction tests, lint/format, wheel build and links/fences in 52 Markdown
files. The SDK test ran with OpenAI Python 2.54.0 (test-only optional dependency).
Mermaid declarations/fences were checked; rendered diagram review remains manual.
Synthetic checks cover standard OpenAI Python
SDK model listing over local HTTP, per-app catalog filtering/authentication, snapshot
expiry/endpoint binding, bounds and built-in parameter/JSON mappings, unsupported
Ollama options before inference, gateway-only hashed user correlation, eligible FIFO,
global/per-app queue overflow, wait timeout, queued cancellation/disconnect cleanup,
slot recovery and bounded-label queue metrics. A queued-request setup-change test preserves the arrival endpoint, credential and
cache while new requests use the updated connection. Shared backend contracts
preserve queue/hash metadata across reopen. Controls persist through restart;
console checks cover the capability matrix and queue setting submission. Schema-3
upgrade tests preserve keys, usage and identity audit while adding nullable fields.
That batch added twelve sample scenarios including catalog/options
and real HTTP queue overflow/recovery.

Live model/provider JSON compliance, Ollama/Windows, vLLM/OpenAI/tunnel integration,
visual browser behavior and final container/native clean-host packaging remain
unverified for this batch. No Docker image was rebuilt and no live user state was
migrated. Streaming and active disconnect cancellation are implemented in the
subsequent batch above; its live provider evidence remains deferred. See the
[inference and queue runbook](runbooks/inference-api-and-queueing.md).

## Managed application keys and identity audit

Schema 3 separates application policies from credential digests. It implements
overlapping replacement keys, optional expiry, individual revocation, an enforced
ten-active-key bound and transactional identity management audit. The console has
Manage keys and Management audit views. Initial/migrated keys preserve existing
behavior; only newly issued replacements receive requested expiry. Audit identifies
the shared operator role and excludes credential values and inference content.

Verified locally: 194 Python tests, 18 console interaction tests, lint/format,
Python wheel build and links/fences in 50 Markdown files. Checks cover shared
adapter lifecycle contracts, schema-1/2 migration, unchanged keys/policies/usage,
inactive legacy keys, expiry, shared rate limits, concurrent issuance bounds,
idempotent/scoped revocation, atomic audit rollback, restart, encrypted recovery
and the sample HTTP replacement-key scenario. Console checks cover overlap, expiry
submission, revocation confirmation, audit project filters, safe rendering and
late secret responses after lock. No live user database was migrated and no
Docker container/image was started, rebuilt or replaced.

Provider/configuration audit is implemented by the later configuration recovery batch.
Individual operator identity, encryption/digest key version migration, remote
adapters/export, visual browser checks and final container packaging remain deferred. See [key lifecycle runbook](runbooks/application-key-rotation.md).

## SQLite backend foundations

The first backend increment extracts configuration, identity, secret, traffic and
usage repositories behind the compatible control API. A trusted named registry
selects SQLite or explicitly registered source extensions. Only SQLite is bundled.
Schema 2 backfills usage from retained traffic before normal pruning; usage is
content-free, independently retained and unaffected by traffic deletion.

Verified locally with isolated synthetic stores: 185 Python tests, 15 console
tests, Python wheel build, lint/format and links/fences in 49 Markdown files. Coverage includes shared
adapter contracts, application startup through a registered factory, key/credential
preservation, independent retention, unknown/cache usage, duplicate delivery,
configuration/credential rollback, traffic/usage rollback, failed migration rollback,
encrypted backup usage preservation and sample HTTP log deletion preserving totals.
No live native or Docker store was migrated. Docker was not started or rebuilt.

PostgreSQL, Vault and exporter implementations/tests remain deferred. Large-history
migration performance, disk-full/crash recovery, cross-release rollback and final
container packaging need separate evidence; best-effort logging is not a lossless
accounting guarantee. See [backend adapters](backend-adapters.md) and
[acceptance/upgrade runbook](runbooks/backend-storage-testing.md).

## Backend discussion and deferred Docker packaging

On 2026-10-05 the development priority changed to backend architecture. The proposal
separates existing SQLite responsibilities without adding default external services,
and calls out independent usage history, secret/key lifecycle, configuration revisions
and reliable export contracts as planned work. No data migration or backend refactor
was performed during this discussion. Docker files/helpers remain available; image
build/publication now requires an explicit CI dispatch with `package_container`.
Routine source pushes retain source/docs/native verification. Final container
acceptance is still required before release. No local containers were started,
stopped or rebuilt for this architecture/documentation change.

## Setup connection test and development workflow

On 2026-10-04, the operator reported successful Docker startup. Read-only inspection
confirmed a healthy local Compose container on loopback port 8087. Its data remains
in its own volume, independent of source/portable storage. No existing database,
volume or container was replaced during this change.

Draft connection probe tests cover auth, reachable/empty Ollama model lists,
network refusal, timeout, upstream rejection, malformed payload, bounded timeout,
no saved-state/key changes, and stored-key protection at changed endpoints.
Console interaction checks exercise the unsaved form, success/failure feedback and
unchanged defaults. Docker helper checks cover explicit update/preserved volume and
mutually exclusive build/update options. All 172 Python tests, 15 console tests,
lint/format, shell/JavaScript syntax and Markdown checks passed. The local Docker
image and isolated run/Compose smoke passed, including the new probe against a
synthetic host endpoint, tokens/content capture, recreation and cleanup. The
operator's existing container stayed healthy and was not replaced.

A separate isolated container tested Ollama at `host.docker.internal:11434` and
returned a safe unreachable result; no completion was generated. This proves the
failure-reporting path, not an Ollama running-state diagnosis. WSL loopback also
failed to reach Ollama during this check. Live successful
Ollama testing and cross-runtime migration remain pending. Hosted CI passed all source/docs/native,
container and publication jobs for `1ea8d68`; see
[CI evidence](https://github.com/m87techlabs/m87-ai-gateway/actions/runs/37246001474).
Local browser checks, live Ollama connection testing from the user's container,
and cross-runtime migration remain separate operator checks.

## Docker workstation helper scripts

On 2026-10-04: 163 Python tests, lint/format, Markdown and shell syntax checks
passed. Prerequisite failure handling and eight isolated
helper tests cover unavailable engine, invalid port, rejected registry pull,
health-wait startup, invocation outside the checkout, source builds, preserving
image/port on resume, scoped stop and missing-service status. The current WSL Docker
shim is unusable; the actual launcher reports the WSL integration prerequisite
and exits without starting services. Host Python is not required by these helpers.

Hosted container CI also exercises the real helpers from outside the checkout:
source build/start on an explicit port, health/status, stop, stopped status and
resume preserving the port/operator key. Its isolated project volume is removed
afterward. The initial hosted helper check passed build/start/status/stop, then
caught an unsupported `compose start --wait-timeout` assumption on resume. Resume
now uses normal Compose start and a bounded Docker health poll. Publication was
blocked for that run. Corrected hosted container/helper checks passed for `427dd61`:
source build/start, health/status, stop, stopped status, and resume with the same
port/operator key, without printing the key. Test containers/volumes were removed.
[CI evidence](https://github.com/m87techlabs/m87-ai-gateway/actions/runs/37244960525).
Local Docker Desktop
and live Windows Ollama checks remain for the operator's next session.

## Single-container distribution phase

On 2026-10-04 the WSL session has no usable Docker command/integration. No local
engine or ecosystem services were started. Container checks run on hosted Linux
CI: image build, Docker run/Compose, non-root private storage, setup, host-gateway
model discovery and synthetic completion, token/content logging, recreation and
shutdown. The first hosted image build passed; its smoke failed during startup because the
HTTP poll did not retry a connection reset before the listener became ready. The
poll now retries transient socket errors within its bounded startup window. That
run published nothing. The next run reached setup and a successful synthetic
completion; its capture assertion selected an earlier authentication-rejection
event before the completion audit write finished. The poll now waits for the
successful test application's event. Neither failed run published an image.
The corrected run passed all jobs, including native bundles and publication.

Hosted Linux container checks passed for `1c811bb`: Docker run and Compose,
non-root UID 10001/private 0700 storage, loopback publishing, root console redirect,
initial readiness/auth rejection, host-gateway inference discovery and completion,
provider-reported tokens, captured input/output, stdout secret/content exclusion,
healthy Docker probe, graceful stop and saved configuration/key/logs after container
recreation. Test containers and volumes were removed. See
[CI evidence](https://github.com/m87techlabs/m87-ai-gateway/actions/runs/37242285889).

Source tests (155), docs/console checks, Windows/Linux packaged setup/recovery
smokes, container smoke and publication all passed for `1c811bb`. CI pushed and
pulled back the immutable GHCR image, then advanced `:preview`. Durable ZIPs,
checksums and Compose are available in
[preview-1c811bbeb4ad](https://github.com/m87techlabs/m87-ai-gateway/releases/tag/preview-1c811bbeb4ad).
Repository visibility and the historical `v0.1.0` tag were preserved.

The image and durable preview downloads are development distribution, not stable
release evidence. Current repository/package visibility remains private. Deferred:
Windows Docker Desktop with live Ollama, clean-host pull/setup, container encrypted
backup/restore, live OpenAI, ARM, cloud hosting, signatures and distinct-version
rollback. These need a Docker-capable host and deliberate provider credentials
where relevant. Synthetic checks make no billable cloud requests.

## Gateway-wide LLM input/output logging

Checked on 2026-10-02: 137 Python tests and 11 browser DOM tests passed. Capture is
controlled by the gateway-wide setting in Setup/YAML/environment. Per-app capture
controls were removed from the console; legacy fields remain accepted and are
ignored for compatibility. Tests cover all combinations of gateway/legacy app
flags, secret redaction, content exclusion from stdout, and real HTTP integration
with an app whose legacy capture flag is false. The standalone smoke also uses
that false flag and checks captured input/output after restart.

The running local gateway was restarted while preserving its data, keys, and port;
gateway-wide capture was enabled in persisted setup. A live sample → gateway →
Windows Ollama request returned HTTP 200 with 19 reported tokens, and the correlated
SQLite log contained both input and output despite the app's legacy flag being
false. Message text and credentials were not printed as validation evidence.
Older uncaptured records cannot be backfilled. Default capture remains off for
new installations; turning it on applies to all authorized, policy-approved
requests in that gateway. Docker and cloud-provider checks remain deferred.

## Official local port and sample lifecycle

Key-prompt follow-up on 2026-10-02: 12 targeted lifecycle tests passed, covering
empty/whitespace-containing keys, unavailable stdin, key privacy, duplicate starts,
source/native launches, fallback ports, and graceful cleanup. Invalid key input is
now rejected at the prompt before launching a sample process. Startup failures
show a port-specific hint only when a listener bind actually failed; raw private
startup logs are not copied to terminal output. Ruff, ShellCheck, documentation,
and whitespace checks passed. Docker and inference were unnecessary.

Checked on 2026-10-02: 133 Python tests, Ruff, ShellCheck, Bash syntax, 44-file
documentation checks, whitespace checks, and a rebuilt Linux executable smoke
passed. The default local gateway listener is reserved on 8087, falling back by
increments of 100 through 65487. Tests exercised actual script startup with 8087
and 8187 occupied, plus listener reservation, exact-port collision, and sequence
exhaustion. Explicit ports remain exact. Foreground CLI, source scripts, and the
standalone executable use the same listener selection.

The sample has separate background start/stop/status scripts, an automatically
allocated local port, private process state/logs, duplicate-start protection,
idempotent stop, and process identity/type checks. Tests verified starting from
another working directory, key privacy, selected-port reporting, and cleanup
without creating a gateway instance. The existing HTTP integration test now runs
the foreground sample CLI; separate lifecycle tests exercise its scripts. Existing
foreground processes require Ctrl+C before switching to managed background startup.
An already-running gateway retains its port until stopped and started again.

No Docker or live-model inference was needed for this lifecycle change. Native
Windows scripts, service installation, and reboot persistence remain deferred.
Container/Flow Lab deployments keep their explicitly configured ports; automatic
fallback is a local launcher feature. See [guided setup](runbooks/guided-setup.md)
and the [chat sample](../examples/chat_app/README.md).

## Model access editing and live sample chat

Checked on 2026-10-02: 127 Python tests, ten browser DOM tests, Ruff, JavaScript
syntax, 44-file documentation checks, and whitespace checks passed. Authenticated
model-access updates preserve the app key and persist in SQLite. Tests cover
unauthorized edits, empty lists, unknown applications, newly allowed requests,
and denial after permission removal. The console can save an existing app's
Models list; the sample maps known provider error codes to useful messages while
discarding raw upstream error text. The standalone smoke now checks model-access
updates followed by restart and inference using the original application key.

A live Windows Ollama session through the running WSL sample and managed gateway
returned HTTP 200 with `ollama:gemma3:1b`, 15 input tokens, four output tokens,
and 19 total tokens. The previous failure was an explicitly disabled Ollama
connection plus a default route for an uninstalled model. Enabling the existing
local connection, selecting the installed model, and extending the existing app's
model permissions resolved it without key replacement. Only the managed gateway
was restarted; other instances and inference processes were preserved. No Docker
or cloud provider call was needed. This verifies live local sample inference;
cloud-provider and visual-browser checks remain deferred.

## Independent chat sample

Custom-port follow-up, checked on 2026-10-02: 125 Python tests and nine browser DOM
tests passed. The sample now discovers the live managed gateway using its private
process identity record, respects an explicit URL/environment override, rejects
stale or broadly readable records, and displays the selected URL. The HTTP flow
check exercises automatic detection of an isolated gateway on a nondefault port.
This prevents defaulting to an older Flow Lab instance on 8080 when the operator's
configured gateway uses another port. Existing running sample processes require
a restart to pick up server changes. Credentials and existing gateway processes
are preserved. Inference in automated checks remains synthetic.

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

## Phase 1 controls and sample acceptance

Checked on 2026-10-02 with Python 3.12 and Node 24 on Linux/WSL:

- Source suite: 143 tests passed, including nine real HTTP sample/gateway/synthetic
  inference scenarios, operator authorization, invalid controls, persisted cache
  initialization, retention on writes/save/restart, migration, scoped deletion,
  readiness credential/storage failures, concurrency isolation and cancellation.
- Console/sample DOM suite: 14 tests passed, including Controls editing, application
  limit updates without key replacement, project deletion confirmation, and sample
  cache/retry display. These do not establish visual/browser/accessibility behavior.
- Experimental Linux executable rebuilt and its smoke checks cover persisted
  controls, application limits, readiness, restart, inference, logs, and token usage.
- Ruff lint/format, JavaScript syntax, Markdown links/fences and whitespace passed.
- The managed source gateway/sample were reloaded on their existing ports without
  changing keys or saved configuration. Controls and `/ready` returned successfully;
  a short Windows Ollama completion returned HTTP 200 with cache-status metadata.
  Live fault/recovery exercises were not run against this inference service.

The isolated scenarios start only temporary loopback services with private temporary
storage and generated credentials; they make no cloud calls and clean up afterward.
They test predictable synthetic failures rather than real Ollama/provider behavior.
Live Ollama fault/recovery exercises, Docker networking, native Windows packaging,
clean-host distribution, multi-replica controls, and cloud adapters/deployments remain
unverified. Docker stayed disabled. See the
[acceptance runbook](runbooks/gateway-controls-testing.md).

## Phase 2 portable preview and recovery

Checked on 2026-10-04 with Python 3.12 on Linux/WSL:

- Full source regression suite: 155 passed. New tests cover encrypted recovery,
  app/provider/operator credential preservation, retained logs/configuration,
  wrong password, tampering, nonempty restore targets, future schemas, duplicate
  directory locks, broad permissions, symlinks, empty master keys, stale instance
  identity and operator-authenticated shutdown.
- Linux standalone executable, portable ZIP, checksum manifest and wheel built.
  The executable smoke passed setup, controls, readiness, native status/stop,
  encrypted backup, restore into fresh data and inference with the restored app key.
- Portable ZIP members, version and binary checksum matched the build manifest.
- Ruff, script syntax, documentation links/fences and whitespace checks passed.
- Hosted Windows Server 2022 x64/Python 3.11 checks passed: 11 platform safety tests
  and one privilege-dependent symlink skip; native executable build; setup, private
  storage, app/provider credentials, status/stop, encrypted backup/restore, readiness
  and restored inference smoke. The Linux bundle job and source/docs jobs also passed.
  [CI evidence for `647d930`](https://github.com/m87techlabs/m87-ai-gateway/actions/runs/37229755678).
- The first Windows run caught unclosed backup SQLite handles during temporary
  snapshot cleanup. The corrected code closes connections explicitly before cleanup;
  the same Windows recovery tests and packaged smoke now pass.
- Both native CI jobs uploaded portable ZIPs and checksums with 14-day artifact
  retention. These are developer-preview artifacts, with no public release tag.
- The managed source gateway was reloaded on its existing 8087 listener and returned
  readiness 200. The stopped sample was left stopped; no live inference fault was induced.

Docker remained disabled and the checks made no cloud calls. Windows Ollama through
the native Windows artifact, clean Windows/Linux workstations, graphical browser
behavior, signed releases and rollback between distinct released versions remain
unverified. CI runners have development tools installed; native CI smoke alone
cannot establish clean-workstation support. No tag, public release or visibility
change was made. See [portable runbook](runbooks/workstation-distribution.md).

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
| Compose validation | Verified in hosted Linux CI; local WSL remains disabled | Running Docker/Compose; no `.env` required | `docker compose config --quiet` exits successfully |
| Image build and container startup | Verified in hosted Linux CI | Working Docker engine and image/dependency download access | Build from the intended commit; container stays running |
| Container health and local port binding | Verified in hosted Linux CI | Start the Compose service | `/health` returns 200; published gateway port is bound to host loopback |
| Container UI setup and persistent volume | Verified in hosted Linux CI, including recreation | Configure inference and create an app key in the console | Valid auth succeeds, missing/invalid auth fails, intended default route is selected |
| Container-to-host Ollama connectivity | Native provider path passed; container path is unverified | Docker plus the reachable Ollama listener and installed model | `host.docker.internal` resolves; a synthetic chat returns the intended model |
| OpenAI end-to-end response | No live provider check performed | Provider credentials, accessible model, and an intentional quota-consuming test session | Synthetic authenticated chat succeeds with the configured OpenAI route |
| Configuration restart and key rotation | Operational path not exercised | Running test instance and synthetic keys | New key works after recreation; retired key fails; safe rollback works |
| Deployment rollback | Rollback across distinct image versions remains unverified | Working current and previous artifacts/configurations | Restore previous version and repeat health/auth/chat checks |

Follow [container deployment](runbooks/container-deployment.md),
[configuration changes](runbooks/configuration-changes.md), and
[provider troubleshooting](runbooks/provider-troubleshooting.md). A local Python
instance can exercise live provider behavior without Docker; container networking
and image checks still require Docker.

## Acceptance criteria still requiring implementation

Enabling Docker does not complete these roadmap items:

- Budget enforcement, response policies, live-provider readiness, cost estimates, and
  durable/remote event delivery remain incomplete or absent.
- AWS Bedrock, Azure OpenAI, Google Cloud Vertex AI, and Anthropic adapters are
  planned; cloud contract/live checks depend on those adapters existing.
- Cloud deployment and migration/restore validation need tested procedures before
  operational support can be claimed. Local SQLite persistence and additive migrations
  are implemented.

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
