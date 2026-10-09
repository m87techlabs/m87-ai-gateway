# Local log receiver example

This loopback webhook receiver stores sanitized gateway metadata in private SQLite
and deduplicates delivery IDs. It is a source-only testing example.

Follow [metadata export](../../docs/runbooks/log-export.md) for token setup, startup,
gateway configuration, outage/restart checks and inspecting received metadata.
The existing chat sample or gateway API tester supplies inference requests.
