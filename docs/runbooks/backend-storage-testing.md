# Backend storage acceptance

## Requirements

Use the repository development environment with `.[dev]` installed. These tests
use temporary SQLite stores and synthetic data. Docker, inference services and
cloud credentials are unnecessary.

```bash
.venv/bin/pytest -q tests/test_backend_contracts.py tests/test_control_store.py tests/test_projects.py tests/test_backup_workstation.py
```

Run the full source suite before publication. Future backend implementations must
run the shared contract described in [backend adapters](../backend-adapters.md),
plus their external-service failure/recovery suite.

## Expected behavior

1. Create projects, application keys, configuration and provider credentials;
   reopen the same store and confirm persistence. Revoke keys and confirm rejection.
2. Record a synthetic exchange twice. Request/token totals count it once.
3. Delete its traffic log. The detail disappears while usage remains. A repeated
   delivery within the usage retention window still counts once.
4. Confirm cache hits add requests and cache counters without new provider tokens.
   Missing token counts remain unknown. Project filters preserve attribution.
5. Record older traffic with short log retention and longer usage retention.
   Traffic expires independently; usage expires only at its own cutoff.
6. Inject a usage-write failure and verify the traffic write rolls back too.
   Inject configuration serialization failure and verify neither settings nor
   provider credentials change.
7. Upgrade a synthetic schema-1 store: retained events populate usage once,
   existing keys still work, and prompt/response columns are absent from usage.
8. Select an unavailable adapter and confirm startup fails without creating local
   storage. Confirm duplicate/reserved registrations are rejected.

## Existing-store upgrade

Before starting this version against an existing store, stop that gateway and take
an encrypted backup with its current binary. Follow the
[workstation backup procedure](workstation-distribution.md). Preserve the matching
master/operator keys and the compatible binary for rollback.

Startup migrates schema 0/1/2 to schema 3 and backfills usage from events that still
exist, before normal retention pruning. It cannot recover already deleted traffic.
Usage defaults to 365 days and traffic to 30 days. Set
`control_plane.usage_retention_days` before startup if a different window is needed.
Pruning runs at startup and event writes; traffic also prunes when Controls is saved.
There is no idle expiry timer. Deleting traffic does not clear usage, JSONL files,
backups, or cached responses and is not secure erasure.

An older schema-1/2 binary rejects a schema-3 database. Rollback requires the earlier
backup restored into a fresh private directory; do not downgrade the live database
or manually change its version. Upgrade checks here use isolated fixtures; no
running workstation or Docker database is migrated by running the tests.

## Deferred gates

Real PostgreSQL/Vault/export adapters, concurrent remote transactions, large-history
migration performance, disk-full/crash recovery, and cross-release rollback need
separate evidence. The existing recorder is best effort: atomic SQLite writes do
not establish lossless accounting. Docker packaging remains deferred until a
functional release checkpoint.
