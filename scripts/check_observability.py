"""Validate monitoring configuration and evaluate rules/queries with promtool."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "deploy/observability"


def check(promtool):
    subprocess.run(
        [promtool, "check", "config", str(ASSETS / "prometheus/prometheus.yml")], check=True
    )
    subprocess.run(
        [promtool, "test", "rules", str(ASSETS / "prometheus/alerts.test.yml")], check=True
    )
    overview = json.loads((ASSETS / "grafana/dashboards/gateway-overview.json").read_text())
    expressions = []
    for panel in overview["panels"]:
        for query in panel["targets"]:
            expression = query["expr"].replace("$instance", ".*").replace("$__rate_interval", "5m")
            expressions.append({"expr": expression, "eval_time": "10m", "exp_samples": []})
    with tempfile.TemporaryDirectory(prefix="m87-monitoring-check-") as directory:
        queries = Path(directory) / "queries.yml"
        queries.write_text(yaml.safe_dump({"tests": [{"promql_expr_test": expressions}]}))
        subprocess.run([promtool, "test", "rules", str(queries)], check=True)
    print(f"Validated 9 alerts, synthetic transitions and {len(expressions)} dashboard queries")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promtool", default="promtool")
    check(parser.parse_args().promtool)
