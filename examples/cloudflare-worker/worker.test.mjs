import assert from "node:assert/strict";
import test from "node:test";

import worker from "./worker.js";

const CLIENT_KEY = "synthetic-client-key-000000000001";
const GATEWAY_KEY = "synthetic-gateway-key-0000000001";

function request(body, key = CLIENT_KEY) {
  return new Request("https://worker.example.invalid", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

test("keeps caller and gateway credentials separate and forwards correlation", async () => {
  const originalFetch = globalThis.fetch;
  let outbound;
  globalThis.fetch = async (url, options) => {
    outbound = { url: String(url), options };
    return new Response('{"id":"synthetic"}', {
      status: 200,
      headers: { "Content-Type": "application/json", "X-Request-ID": "request-123" },
    });
  };
  try {
    const response = await worker.fetch(request({
      model: "auto",
      messages: [{ role: "user", content: "synthetic prompt" }],
    }), {
      CLIENT_API_KEY: CLIENT_KEY,
      GATEWAY_API_KEY: GATEWAY_KEY,
      GATEWAY_URL: "https://gateway.example.invalid/original/path",
      GATEWAY_ACCESS_CLIENT_ID: "synthetic-access-id",
      GATEWAY_ACCESS_CLIENT_SECRET: "synthetic-access-secret",
    });

    assert.equal(response.status, 200);
    assert.equal(response.headers.get("X-Request-ID"), "request-123");
    assert.equal(outbound.url, "https://gateway.example.invalid/v1/chat/completions");
    assert.equal(outbound.options.headers.get("Authorization"), `Bearer ${GATEWAY_KEY}`);
    assert.equal(outbound.options.headers.get("CF-Access-Client-Id"), "synthetic-access-id");
    assert.equal(JSON.parse(outbound.options.body).stream, false);
    assert.doesNotMatch(outbound.options.body, /synthetic-client-key/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fails before the gateway for bad caller credentials or unsupported fields", async () => {
  const environment = {
    CLIENT_API_KEY: CLIENT_KEY,
    GATEWAY_API_KEY: GATEWAY_KEY,
    GATEWAY_URL: "https://gateway.example.invalid",
  };
  assert.equal((await worker.fetch(request({ messages: [] }, "wrong-key"), environment)).status, 401);
  assert.equal((await worker.fetch(request({ messages: [], stream: true }), environment)).status, 422);
  assert.equal((await worker.fetch(request({ messages: [], tools: [] }), environment)).status, 422);
});

test("fails closed for unsafe or incomplete origin configuration", async () => {
  const body = { messages: [{ role: "user", content: "synthetic" }] };
  const base = { CLIENT_API_KEY: CLIENT_KEY, GATEWAY_API_KEY: GATEWAY_KEY };
  assert.equal((await worker.fetch(request(body), {
    ...base, GATEWAY_URL: "http://gateway.example.invalid",
  })).status, 503);
  assert.equal((await worker.fetch(request(body), {
    ...base,
    GATEWAY_URL: "https://gateway.example.invalid",
    GATEWAY_ACCESS_CLIENT_ID: "id-without-secret",
  })).status, 503);
});
