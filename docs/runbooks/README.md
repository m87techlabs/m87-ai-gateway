# Runbooks

Step-by-step procedures for running the gateway.

## Get started

| Runbook | Use it to |
| --- | --- |
| [Run with Docker](container-deployment.md) | Start, stop, configure, back up and upgrade |
| [Guided setup](guided-setup.md) | Go from a running gateway to your first request |
| [Daily operations](daily-operations.md) | Everyday checks and log inspection |
| [Provider troubleshooting](provider-troubleshooting.md) | Diagnose connection and model failures |
| [Incident response](incident-response.md) | Handle a gateway failure |

## Apps, usage and limits

| Runbook | Use it to |
| --- | --- |
| [Projects and usage](projects-and-usage.md) | Group applications and read per-app reports |
| [Application key rotation](application-key-rotation.md) | Rotate keys without downtime |
| [Traffic controls](traffic-controls.md) | Set limits, queueing, retries and caching |
| [Inference API and queueing](inference-api-and-queueing.md) | Use and test the API |
| [Streaming and cancellation](streaming-and-cancellation.md) | Understand stream outcomes and errors |

## Logs and monitoring

| Runbook | Use it to |
| --- | --- |
| [Traffic logging](traffic-logging.md) | Control what is recorded |
| [Logging showcase](logging-showcase.md) | Follow one request through Logs |
| [Log export](log-export.md) | Understand metadata delivery to a webhook |
| [Configure log export](configure-log-export.md) | Set up a destination in the console |
| [Loki export](loki-export.md) | Send metadata to Loki |
| [Monitoring with Grafana](grafana-monitoring.md) | Run dashboards and alerts with Compose |

## Configuration and recovery

| Runbook | Use it to |
| --- | --- |
| [Control plane](control-plane.md) | Understand the console and its API |
| [Configuration changes](configuration-changes.md) | Change settings safely |
| [Configuration recovery](configuration-recovery.md) | Restore settings and check storage |

## Developing and releasing

| Runbook | Use it to |
| --- | --- |
| [Local development](local-development.md) | Build, run and test from source |
| [Gateway controls testing](gateway-controls-testing.md) | Exercise limits with the sample app |
| [End-to-end flow testing](end-to-end-flow-testing.md) | Test the Worker, tunnel and gateway path |
| [Backend storage testing](backend-storage-testing.md) | Check storage changes and migrations |
| [Release](release.md) | Publish a version |

## Writing runbooks

Each implemented operator workflow needs a runbook with prerequisites, commands, success checks,
troubleshooting and shutdown. Link it here. Use generic examples, and never include real keys.
