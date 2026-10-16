# Optional monitoring assets

Use these with your own Prometheus, Grafana and optionally Loki. They do not start
services or change gateway setup. The gateway remains useful without them.

- `prometheus/prometheus.yml`: private workstation scrape example, default port 8087.
- `prometheus/alerts.yml`: nine alert rules; notifications require your Alertmanager.
- `prometheus/alerts.test.yml`: synthetic firing, hold and recovery tests.
- `grafana/dashboards/gateway-overview.json`: traffic, tokens, latency and logging health.
- `grafana/dashboards/gateway-logs.json`: Loki metadata filtered by project/app/request.
- `grafana/provisioning/`: optional datasource/dashboard templates; edit server URLs
  and dashboard path for your deployment. No credentials are included.

Start with the [monitoring runbook](../../docs/runbooks/grafana-monitoring.md). In a
standalone ZIP, these files are under `observability/` with `MONITORING.md` beside it.
Only structural/metric/query/rule and native packaging checks are automated here;
actual Grafana rendering and live Loki ingestion/querying remain separate checks.
