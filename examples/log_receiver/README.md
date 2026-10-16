# Local log receiver example

This loopback webhook receiver stores sanitized gateway metadata in private SQLite
and deduplicates delivery IDs. It is a source-only testing example.

Follow [metadata export](../../docs/runbooks/log-export.md) for token setup, startup,
gateway configuration, outage/restart checks and inspecting received metadata.
The existing chat sample or gateway API tester supplies inference requests.

Configure and test this receiver from the gateway’s **Log export** screen using
[console setup](../../docs/runbooks/configure-log-export.md).

The same process accepts `/loki/api/v1/push` for the gateway’s fixed-label JSON
format and normalizes entries into its delivery table. This is a protocol test double,
not a Loki server: no queries/indexing/retention/Grafana are implemented. Its ID-based
deduplication does not establish Loki behavior. See [Loki showcase](../../docs/runbooks/loki-export.md).
