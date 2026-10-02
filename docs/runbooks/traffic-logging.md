# Enable and inspect LLM traffic logging

## Trigger and prerequisites

Use this procedure to inspect how a test application calls a model and what
completion the gateway returns. Start with synthetic messages, one gateway
process, private writable storage, and gateway-wide capture enabled.
Docker is needed only for the container variant.

## Configure and verify

1. Follow the [observability configuration](../observability.md). Set a traffic
   file path or enable the local control store, then enable capture in gateway
   Setup or configuration. This applies to all authorized applications.
   Replace example keys in ignored configuration only.
2. For a native process, run from the intended working directory so the relative
   path resolves predictably. For Docker, mount a private directory/volume at the
   configured path before enabling capture. Do not place it under a web/static root.
3. Ensure existing files have owner-only permissions and the process can write
   them. The gateway fails startup if the configured sink cannot initialize safely.
4. Restart/recreate the service. Send one synthetic chat and retain the
   `X-Request-ID` response header. In a Worker relay, explicitly copy this header
   to the client response.
5. Inspect the private JSONL file locally. For example:

   ```bash
   python - <<'PY'
   import json
   from pathlib import Path

   for line in Path("var/log/gateway/traffic.jsonl").read_text().splitlines()[-5:]:
       event = json.loads(line)
       print(event["request_id"], event["status_code"], event.get("error_type"))
   PY
   ```

6. Match the request ID to the event. Inspect content in the private file or the
   authenticated gateway console's Logs → request detail → LLM input/LLM output.
   Confirm stdout and `/metrics` contain metadata/aggregates without prompt text.
7. Send a request with an invalid key and a blocklisted synthetic prompt. Confirm
   rejection events exist and contain no request/response content.

## Success checks

- The valid exchange has the matching ID, selected model, status, and response.
- Content appears for authorized exchanges while gateway capture is enabled,
  with truncation flags when needed. Older uncaptured exchanges remain unchanged.
- Known app/provider keys are redacted; response delivery is unchanged.
- Rotated files remain private and the sink-error counter stays at zero.

## Failure and recovery

If `traffic_log_write_failed` appears, inspect permissions, free disk space, and
mount availability locally. Error events deliberately omit file paths and content.
A runtime sink failure does not block chat; account for the missing audit records.

To stop capturing content, turn off capture in Setup, or set the global switch to
false in startup configuration and restart. Existing
files remain until rotated or explicitly removed under your retention policy.
Before deleting them, decide whether an investigation requires preservation.
Do not restore broadly readable permissions to make startup succeed.

## Resource and retention policy

Keep a small size/backup count for local tests and stop project containers when
the session ends. Rotation is based on size, not time. A later central log sink
must define time retention and access controls before content is exported.
