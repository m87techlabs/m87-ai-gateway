"""Reconstruct isolated pre-schema-3 fixtures for upgrade tests."""


def schema_two_identities(connection):
    rows = connection.execute("""SELECT a.app_id, k.key_digest, k.key_prefix, a.allowed_models,
        a.capture_content, a.rate_limit_per_minute, a.enabled, a.created_at,
        a.project_id, a.max_concurrent_requests FROM applications a
        JOIN app_keys k USING(app_id)""").fetchall()
    connection.execute("DROP TABLE app_keys")
    connection.execute("DROP TABLE applications")
    connection.execute("DROP TABLE management_events")
    connection.execute("""CREATE TABLE app_keys (
        app_id TEXT PRIMARY KEY, key_digest TEXT NOT NULL UNIQUE, key_prefix TEXT NOT NULL,
        allowed_models TEXT NOT NULL, capture_content INTEGER NOT NULL DEFAULT 0,
        rate_limit_per_minute INTEGER, enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT 'default',
        max_concurrent_requests INTEGER
    )""")
    connection.executemany("INSERT INTO app_keys VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.execute("PRAGMA user_version = 2")
