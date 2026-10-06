# Local logging showcase

## Trigger and prerequisites

Use this procedure to demonstrate how the gateway records an application's LLM
interaction. Use synthetic prompts, the native/source gateway, private operator
access, an application key and a reachable supported inference backend. Docker is
unnecessary for the local showcase. Keep provider secrets in the gateway.

Before upgrading an existing instance, create an encrypted offline backup using the
[workstation runbook](workstation-distribution.md). Schema 7 moves existing retained
content into `exchange_content`, preserves metadata/usage/keys/configuration/audit,
and leaves legacy content columns empty. Older binaries reject the new schema;
rollback uses a compatible backup restored into a fresh destination. Tests do not
migrate a live operator store.

## Demonstrate one exchange

1. Start the gateway with `./start.sh`. Open its printed console URL.
2. In **Setup**, test/save the inference connection, choose a model and enable
   **Capture LLM input and output for all applications**.
3. In **Controls**, choose metadata/content retention and a capture limit large enough
   for the demonstration (for example, 4,096 characters). Capture settings affect
   new requests; older missing content cannot be reconstructed.
4. Create an application key with the chosen/default model allowed. Start the sample:

   ```bash
   ./examples/chat_app/start.sh
   ```

5. Submit a short synthetic prompt. Inspect its response, input/output/total tokens
   and request ID. Choose **Open gateway log**. Authenticate as operator in the
   gateway console; the link contains the request ID and no credentials.
6. In **Logs**, confirm the matching row. Open it to see readable **LLM input** and
   **LLM output**, expandable captured JSON, separate token counts, route, final
   outcome, HTTP status, cache/retries, latency and any partial/truncation flags.
7. Repeat with **Stream response**. Try **Stop** and an unavailable backend to inspect
   partial/cancelled/failed outcomes. Backend computation stopping is a separate
   live-provider check; closing HTTP alone does not prove compute/billing stops.
8. Check recording-health status and destination counters. A failed write can leave
   a gap even when inference succeeds. Use **Storage health** to investigate.

Events are finalized after completion/failure/cancellation. A link opened while
inference is active can show no result yet; refresh after completion or Stop.
Recording also finishes asynchronously after response delivery; allow a short delay.
Older/newer controls browse 250 records per page. Request ID and application filters
match exactly; outcome separates success from failed/cancelled. Project selection
applies to queries. Cursor ordering uses creation time and request ID; it is not a
frozen snapshot when records are modified/deleted during browsing.

## Content lifecycle and privacy

SQLite metadata and content default to 30 days; usage defaults to 365 days. Set
`control_plane.content_retention_days`, `GATEWAY_CONTENT_RETENTION_DAYS`, or the
Controls field to expire captured text earlier. Content expiry is enforced on
reads; expired rows are physically pruned on writes, restart and controls save.
Deleting/expiring metadata cascades to content, even if content retention is longer.
SQLite limits do not control a separately configured JSONL file, which rotates by
size. Capture fields are bounded/redacted text, with filesystem privacy rather than
individual content encryption. Redaction does not guarantee removal of all sensitive
text; use synthetic content for the demonstration.

Content detail distinguishes:

| Status | Meaning |
| --- | --- |
| Captured | Stored content available |
| Truncated | Stored prefix reached the configured character limit |
| Partial / partial truncated | Stream ended without a complete response |
| Disabled | Gateway capture was disabled for that request |
| Not captured | Request did not reach permitted content capture |
| Not produced | No output was captured before failure/cancellation |
| Expired | Recorded content is outside retention or absent from retained storage |
| Deleted | Operator removed content while retaining metadata |
| Unknown | Historical record has no evidence of the capture policy |

Disabling capture leaves previous content under its retention policy. To remove it,
choose **Delete captured content**, confirm the selected project/all-project scope,
and verify metadata and usage remain. Search filters do not narrow deletion scope.
**Delete logs** removes metadata and content but preserves independent usage. Both
explicit deletion actions are audited transactionally. In-flight requests and
separate JSONL files are unaffected. Deletion is logical removal; old SQLite pages,
WAL, backups and downloaded exports are not a secure-erasure guarantee.

JSON exports default to metadata and include up to 1,000 newest matching records
in the UI. Select **Include captured input/output** only when needed. API clients use
`include_content=true`; API export limits are bounded at 10,000. Exports honor
project/request/application/outcome filters and content retention, but are not a
complete archive. Treat content downloads as sensitive files.

## API and recording health

- `GET /admin/api/logs?request_id=...&app_id=...&status=error&limit=100`
- Continue with the returned `next_cursor` through the `cursor` query parameter.
- `GET /admin/api/logs/{request_id}` includes retained content and capture states.
- `GET /admin/api/logs/export?include_content=false` exports metadata by default.
- `DELETE /admin/api/logs/content` takes `{"confirmation":"DELETE","project_id":"default"}`.
- `GET /admin/api/logging-health` reports current capture/retention and private
  destination success/failure counts with last success/failure timestamps.

All these operations require the operator key. Projects currently group records;
they do not create separate operator/tenant access boundaries. Health counts reset
on restart and describe completed writes, not crash durability. A successful later
write marks recovery while cumulative failed-write counts remain visible. No raw
exceptions, captured text, secrets or paths appear in this report. Prometheus's
log-write error counter remains available. Metadata stdout/metrics omit input/output.

## Automated acceptance and recovery

Run from the repository root:

```bash
.venv/bin/pytest -q tests/test_logging_showcase.py tests/test_backend_contracts.py
.venv/bin/python -m examples.chat_app.scenarios
cd tests/console
npm test
```

The 16-scenario sample suite includes exact request lookup, captured input/output,
provider-reported tokens, metadata/content export separation, content deletion and
recording health. Tests additionally cover schema-6 preservation, atomic writes,
independent retention on reads, pagination ties, malformed cursors, project filters,
operator-only access, redaction/truncation, writer failure/recovery and safe browser
rendering. Native smoke checks the same logging APIs through a packaged executable
and encrypted backup/recovery.

On a write failure, inspect **Storage health**, available disk, owner-only permissions
and competing writers. Preserve failed-store evidence and use encrypted recovery
when required; do not regenerate keys or grant broad permissions. Local recording
remains best effort. Durable outbox delivery, Loki/OTLP/webhook exporters, traces and
managed Grafana services are planned in [logging plan](../logging-plan.md).
Record live Ollama/browser/tunnel/Docker results separately in [validation](../validation.md).
