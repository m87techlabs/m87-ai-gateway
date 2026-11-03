"""A fake OpenAI-compatible server and log receiver for tests that need no real provider."""

import json
from http.server import BaseHTTPRequestHandler


class Inference(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, body):
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        self.reply({"data": [{"id": "synthetic-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/loki/api/v1/push":
            assert self.headers["Authorization"] == "Bearer synthetic-export-token"
            stream = body["streams"][0]
            assert stream["stream"] == {
                "service_name": "m87-ai-gateway",
                "log_kind": "llm_exchange",
            }
            timestamp, line = stream["values"][0]
            assert isinstance(timestamp, str) and timestamp.isdigit()
            event = json.loads(line)
            with self.server.delivery_lock:
                self.server.deliveries.setdefault(event["delivery_id"], event)
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/events":
            assert self.headers["Authorization"] == "Bearer synthetic-export-token"
            assert self.headers["Idempotency-Key"] == body["delivery_id"]
            with self.server.delivery_lock:
                self.server.deliveries.setdefault(body["delivery_id"], body)
            self.reply({"accepted": True})
            return
        assert body["model"] == "synthetic-model"
        assert self.headers["Authorization"] == "Bearer synthetic-provider-key"
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            base = {
                "id": "chatcmpl-bundle",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "synthetic-model",
            }
            values = [
                {
                    **base,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "synthetic answer"},
                            "finish_reason": "stop",
                        }
                    ],
                },
                {
                    **base,
                    "choices": [],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                },
            ]
            for value in values:
                self.wfile.write(f"data: {json.dumps(value)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self.reply(
            {
                "id": "chatcmpl-bundle",
                "object": "chat.completion",
                "created": 1,
                "model": "synthetic-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "synthetic answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }
        )
