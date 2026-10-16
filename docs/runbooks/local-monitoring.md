# Start local Grafana and alerts without Docker

## Prerequisites

This optional source-checkout helper supports **Linux/WSL x86-64** with a current
Python 3.11+ providing safe tar extraction. It downloads pinned official Grafana OSS
and Prometheus binaries when requested, verifies SHA-256 checksums, and runs them as
your user. No sudo, Docker, global package install or virtual-environment activation
is required. Native Windows, ARM and automatic boot startup are not supported by
this helper. The gateway itself still supports its documented native distributions.

Allow roughly 0.6 GB for initial downloads plus extracted tools/data. Keep adequate
space for seven days of Prometheus history. Downloads require access to the official
Grafana and GitHub release hosts. The tool cache is private to this project and is
not included in Git or the gateway's encrypted backup.

## Start and sign in

From the source checkout root:

```bash
./start.sh
./monitoring-start.sh --install
```

`--install` permits downloading missing tools. Cached archives are verified before
extraction; subsequent starts reuse the installed tools. The verified versions are
Grafana OSS **13.2.4** and Prometheus LTS **3.13.4**. Version/checksum changes require
an explicit source update; this helper does not silently upgrade services. Reference:
[Grafana download](https://grafana.com/grafana/download/13.2.4?edition=oss&platform=linux),
[Prometheus download](https://prometheus.io/download/).

The helper detects the managed gateway's saved port with process identity checks,
then verifies its health and metrics. If the gateway is managed elsewhere, pass its
loopback URL explicitly:

```bash
./monitoring-start.sh --gateway-url http://127.0.0.1:8187
```

By default Grafana uses `http://localhost:3000`, and Prometheus uses
`http://localhost:9090`. If occupied, monitoring tries the next free port and reports
its actual URLs. All listeners bind only to `127.0.0.1`. Existing services are left
running. Windows browsers normally reach these WSL services through localhost
forwarding; verify that setting if your browser cannot connect.

Grafana login: **admin**. Read the generated initial password locally:

```bash
cat var/lib/monitoring/grafana-admin-password
```

The file is owner-only, ignored by Git and never printed by the helper. Keep it
private. If you change the password in Grafana, use your new password thereafter;
the initial file is not updated. Restarting does not reset the database password.
If existing Grafana data remains but the initial file is missing, the helper fails
rather than inventing a misleading replacement. Restore the file or use the
installed Grafana's documented administrative recovery procedure.

Open **Dashboards → M87 Gateway → M87 Gateway Overview** and select **M87 Prometheus**
and the gateway instance. The helper provisions the datasource and overview from the
repo templates into a separate private runtime directory. It does not overwrite any
other Grafana installation. New accounts/signups and anonymous access are disabled;
external plugin preinstallation and analytics/update checks are disabled.

Allow two 15-second scrapes before expecting rates. Send a synthetic request from
the sample app or API tester to populate request/token panels. Empty traffic or
unknown provider usage stays unknown; do not mistake an empty rate graph for a
failed scrape. No fake requests or usage are inserted during setup.

## Alerts

Open the reported Prometheus URL with `/alerts`, normally
`http://localhost:9090/alerts`. All nine included rules load automatically. Scrape
availability and log health evaluate independently of request traffic; error/latency
rules include hold periods and a traffic floor. Review/tune thresholds as described
in [monitoring configuration](grafana-monitoring.md#3-review-alert-thresholds-and-routing).

**Notifications are not configured.** No email, webhook, chat or paging destination
is included. Add a private Alertmanager integration and verify its routing when you
choose a destination. A locally firing rule does not establish message delivery.

The helper provisions metrics only. It does not launch Loki or configure remote
input/output export. Add an existing Loki datasource and the metadata dashboard
using [Loki operations](loki-export.md) when needed. Captured LLM input/output remains
in the gateway's operator-authenticated local Logs page.

## Status, stop and restart

```bash
./monitoring-status.sh
./monitoring-stop.sh
./monitoring-start.sh
```

Repeated start reuses an already running managed stack. Stop signals only processes
whose PID, Linux start ticks and command digest match the private saved state. It
leaves the gateway, other services, downloads, dashboards, metrics history and login
credentials intact. A partially running stack requires stop then start; the helper
will not adopt unrelated listeners or terminate reused PIDs. Stop only the gateway
with `./stop.sh` when you are finished with it separately.

The helper runs native background processes; it does not register system services.
After WSL shutdown, start the gateway and monitoring again. A dashboard template
change is copied into runtime provisioning on the next monitoring stop/start.

## Private files and backup

All runtime state is under `var/lib/monitoring/` by default:

| Path | Purpose |
| --- | --- |
| `tools/`, `downloads/` | Verified local tools and cached archives |
| `config/` | Generated datasource, dashboard and scrape settings |
| `grafana-data/` | Grafana SQLite database and local settings |
| `prometheus-data/` | Seven-day time-series history |
| `logs/` | Private process startup logs |
| `processes.json`, `lifecycle.lock` | Process ownership and serialized lifecycle operations |
| `grafana-admin-password` | Initial Grafana password; mode 600 |

Use `--data-dir /absolute/private/directory` consistently on start/stop/status to
isolate another installation. The root must be owner-only (mode 700), generated config/credentials/state use
mode 600, and no symlink root is accepted. Do not share this directory or commit its
contents. Back up monitoring data separately while its processes are stopped; the
gateway backup does not contain these services.

If an encrypted pre-upgrade gateway snapshot and separate password were created
during setup, they may be under private `var/lib/monitoring/recovery/`. The helper
does not create gateway backups itself. Preserve recovery files before removing
runtime directories; move their secrets to your own backup location.
This is operational state, not part of the public repository. Restore procedures
remain in [workstation recovery](workstation-distribution.md#backup-and-restore).

## Troubleshooting and verification

| Symptom | Action |
| --- | --- |
| Missing tool | Run `./monitoring-start.sh --install` to permit the pinned download. |
| Checksum mismatch | Preserve data; remove only the indicated cached archive, then retry. Do not bypass verification. |
| Incomplete tool directory | Stop monitoring, preserve data, remove only the named incomplete directory under `tools/`, and retry installation. |
| Gateway unavailable | Start it, check `./status.sh`, or pass the correct loopback `--gateway-url`. |
| Metrics unavailable | Check gateway metrics are enabled. The helper never passes provider/operator keys to Grafana. |
| Partially running stack | Stop then start the managed monitoring stack; unrelated services remain untouched. |
| Service exits | Inspect its private file in `var/lib/monitoring/logs/`; check free disk, tool dependencies and selected ports. |
| Browser cannot connect | Check reported port and Windows/WSL localhost forwarding. Bindings remain private. |
| Login fails after changing password | Use your new password; the initial file is only a bootstrap credential. |

Automated verification:

```bash
.venv/bin/python -m pytest -q tests/test_monitoring_services.py
.venv/bin/python scripts/check_observability.py --promtool var/lib/monitoring/tools/prometheus-3.13.4.linux-amd64/promtool
```

The helper tests cover ownership, unrelated-process preservation, private files,
checksum/missing-download behavior, stable passwords, loopback configuration and
managed gateway fallback ports. Live setup verified Grafana health, provisioning,
24 queries through its datasource, gateway scrape and nine healthy rules. Visual
browser review, a real notification destination and live Loki are separate checks.
See [validation](../validation.md).
