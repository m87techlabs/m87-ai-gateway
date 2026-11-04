# What has been verified

What was actually checked, and what was not. A feature being implemented does not mean it has been
checked against every provider or platform. Earlier checks are in the Git history of this file.

## Status for 0.1.2

| Area | Status |
| --- | --- |
| Chat, streaming, embeddings through Ollama 0.40 on an RTX 5080 | Verified live |
| Horizon, a production RAG app, running through the gateway | Verified live in daily use |
| Cloudflare Worker, Access and tunnel path | Verified live, including that the console and `/metrics` are not routed |
| Docker Compose on Docker Desktop with WSL2 | Verified |
| Quickstart from the published image, with no registry login | Verified on 0.1.2 |
| Compose on a Linux CI runner, with a synthetic model server | Verified on each push |
| Backup and restore through Compose | Verified |
| Prometheus, Grafana and Loki through the monitoring profile | Verified live |
| Console in Chrome, in both themes | Verified |
| arm64 image | Checked to start under emulation only |
| OpenAI and other compatible providers | **Not checked live** |
| Tool calls through the gateway with a real model | **Not checked live**; synthetic tests only |
| Linux host with a real model server | **Not checked** |
| macOS | **Not checked** |
| Cloud hosts | **Not checked**; see the [roadmap](roadmap.md) |
| Safari, Firefox and screen readers | **Not checked** |
| Upgrade or rollback between released versions | **Not checked** |

## Quickstart as a new user: 2026-11-04

In an empty folder on Docker Desktop with WSL2, with no registry credentials: the release's Compose file
downloaded, 0.1.2 pulled anonymously, and the gateway was healthy about 10 seconds later. Connecting Ollama,
creating an application and sending a request through the API returned a real answer. The image is
published for linux/amd64 and linux/arm64, and reported its commit. This used the API rather than the
console's pages.

## Compose packaging and monitoring: 2026-11-03

On Docker Desktop with WSL2, using an isolated Compose project built from a checkout:

- `docker compose --profile monitoring up -d --build` brought up the gateway, Prometheus, Grafana and
  Loki, and all became healthy. Stopping them kept data, and starting only the gateway left the rest off.
- Prometheus scraped the gateway, with per-application token metrics and all 9 alert rules healthy.
- Grafana's datasources reported healthy, both dashboards were provisioned, and all 27 overview queries
  succeeded through its API. Dashboards were not reviewed by eye.
- Log export delivered real request metadata to Loki through the console's settings, with no prompt or
  response content in the lines.

Backup and restore followed the documented commands: an encrypted archive contained no readable
application name, restoring into a separate project worked, and the restored application and operator
keys both authenticated. A secret scan of the full Git history found no real secrets; its 4 findings
are test fixtures and demo keys.

## Rebuilt console: 2026-11-03

A throwaway gateway was driven in headless Chrome at 1440 pixels against Ollama on an RTX 5080, from an
empty store: connect a provider, set a default model, create an application, stream an answer in the
Playground, open its log, turn capture on and read the input and output, edit a blocklist that then
blocked real traffic, see Overview update without a refresh, refresh and stay signed in, restore an
earlier configuration, rotate a key, stop the gateway and watch the page report it and recover, lock,
and confirm a refresh did not sign back in. All 25 checks passed with no script or CSP errors.

Screens were reviewed at 1440 pixels in both themes, and the overview and navigation at 420 pixels.

## Per-application reporting: 2026-11-03

A backup of a live schema-10 store upgraded to schema 11 in an isolated container, keeping usage and
application keys. With two applications on a real GPU, overview, usage, logs and metrics separated them
correctly, and each key's last use was recorded.

## Drop-in API on a real GPU: 2026-11-03

Horizon's real client code ran against the gateway on Docker Desktop, with Ollama 0.40.13 running natively
on Windows, needing only an application key.

| Check | Through gateway | Direct to Ollama |
| --- | --- | --- |
| First streamed token, ~20k character prompts, median of 6 | 988 ms | 993 ms |
| Short completion, warm, median of 7 | 40 ms | 33 ms |
| Batch of 32 embeddings, warm, median of 8 | 180 ms | 151 ms |

Embeddings were byte-identical to direct Ollama. GPU use fell from 97% to 1% within about a second of a
client disconnecting, so generation stops on this server. Idle memory was about 44 MiB. Latency through
the real tunnel has not been measured.

## Rules for this page

- State the version, environment and what was done. Say what was not checked.
- Docker stays off in routine development on a resource-limited machine. List the checks that need it,
  run them together, and stop project containers afterward.
