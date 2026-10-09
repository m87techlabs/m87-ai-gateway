"""Loopback demonstration receiver; never use as a public log service."""

import argparse
import json
import os
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from m87_gateway.private_storage import prepare_file


class Receiver(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self.path != "/events":
            return self.reply(404)
        expected = f"Bearer {self.server.token}"
        if not secrets.compare_digest(
            self.headers.get("Authorization", "").encode(), expected.encode()
        ):
            return self.reply(401)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32768:
                return self.reply(413)
            value = json.loads(self.rfile.read(length))
            delivery_id = value["delivery_id"]
            if (
                value.get("schema_version") != 1
                or not isinstance(delivery_id, str)
                or len(delivery_id) != 32
                or self.headers.get("Idempotency-Key") != delivery_id
                or not isinstance(value.get("event"), dict)
            ):
                return self.reply(400)
            with sqlite3.connect(self.server.database) as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO deliveries VALUES (?, ?)",
                    (delivery_id, json.dumps(value)),
                )
        except (KeyError, TypeError, ValueError):
            return self.reply(400)
        except sqlite3.Error:
            return self.reply(503)
        self.reply(204)


def make_server(database, token, port=0):
    if not token or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("Set a non-empty ASCII receiver token without whitespace")
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    prepare_file(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS deliveries(delivery_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
    server = ThreadingHTTPServer(("127.0.0.1", port), Receiver)
    server.daemon_threads = True
    server.database = str(database)
    server.token = token
    return server


def main():
    parser = argparse.ArgumentParser(description="Local metadata webhook receiver")
    parser.add_argument("--port", type=int, default=9087)
    parser.add_argument("--database", default="var/lib/log-receiver/deliveries.db")
    options = parser.parse_args()
    try:
        server = make_server(
            options.database, os.getenv("M87_LOG_RECEIVER_TOKEN", ""), options.port
        )
    except (ValueError, OSError):
        parser.exit(1, "Receiver could not start. Check token, free port and private storage.\n")
    print(f"Metadata receiver: http://127.0.0.1:{server.server_port}/events", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
