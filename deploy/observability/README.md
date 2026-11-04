# Monitoring assets

Configuration for the optional monitoring profile: `docker compose --profile monitoring up -d`. You can
also use these with your own Prometheus, Grafana and Loki. The gateway works without them.

- `prometheus/prometheus.yml`: scrape configuration for the Compose network.
- `prometheus/alerts.yml`: nine alert rules.
- `alertmanager/alertmanager.yml`: collects alerts, and sends nothing until you add a destination.
- `loki/loki.yml`: Loki with 30-day retention.
- `prometheus/alerts.test.yml`: synthetic firing, hold and recovery tests.
- `grafana/dashboards/gateway-overview.json`: traffic, tokens, latency and logging health, including per application.
- `grafana/dashboards/gateway-logs.json`: Loki metadata filtered by project, application and request.
- `grafana/provisioning/`: datasource and dashboard provisioning. No credentials are included.

See the [monitoring runbook](../../docs/runbooks/grafana-monitoring.md).
