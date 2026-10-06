import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {setTimeout as delay} from "node:timers/promises";
import test from "node:test";
import {JSDOM} from "jsdom";

const root = new URL("../../examples/chat_app/static/", import.meta.url);
async function until(predicate) {
  for (let i = 0; i < 100; i++) { if (predicate()) return; await delay(5); }
  assert.fail("Chat interaction did not complete");
}
async function fixture(t, chatResponse) {
  const dom = new JSDOM(readFileSync(new URL("index.html", root), "utf8"), {url: "http://localhost:8790", runScripts: "outside-only"});
  t.after(() => dom.window.close());
  const {window} = dom;
  window.TextDecoder = TextDecoder;
  const style = window.document.createElement("style");
  style.textContent = readFileSync(new URL("styles.css", root), "utf8");
  window.document.head.append(style);
  assert.ok(style.sheet.cssRules.length > 0);
  const requests = [];
  window.fetch = async (url, options) => {
    if (url === "/api/status") return new Response(JSON.stringify({gateway_reachable: true, gateway_url: "http://127.0.0.1:8181", model: "auto"}));
    assert.ok(["/api/chat", "/api/chat/stream"].includes(url));
    assert.deepEqual(Object.keys(options.headers), ["Content-Type"]);
    const body = JSON.parse(options.body);
    requests.push(body);
    return chatResponse(body, requests.length, options);
  };
  window.eval(readFileSync(new URL("app.js", root), "utf8"));
  const $ = (id) => window.document.getElementById(id);
  const send = (text) => {
    $("prompt").value = text;
    $("chat-form").dispatchEvent(new window.Event("submit", {bubbles: true, cancelable: true}));
  };
  await until(() => $("status").textContent.includes("Ready"));
  return {$, send, requests};
}
const reply = () => new Response(JSON.stringify({content: "<script>untrusted model text</script>", model: "ollama:sample", usage: {prompt_tokens: 8, completion_tokens: 5, total_tokens: 13}, request_id: "sample-request", cache_status: "HIT", latency_ms: 12}));

test("chat renders text safely, forwards history, and clears the conversation", async (t) => {
  const {$, send, requests} = await fixture(t, reply);
  assert.equal($("gateway").textContent, "Gateway: http://127.0.0.1:8181");
  send("Synthetic question");
  await until(() => !$("send").disabled);
  assert.equal($("total-tokens").textContent, "13");
  assert.equal($("cache-status").textContent, "HIT");
  assert.equal($("request-id").textContent, "sample-request");
  assert.equal($("messages").querySelectorAll("script").length, 0);
  assert.ok($("messages").textContent.includes("<script>"));
  send("Follow-up");
  await until(() => !$("send").disabled);
  assert.deepEqual(requests[1].messages.map((m) => m.role), ["user", "assistant", "user"]);
  $("clear").click();
  assert.equal($("messages").textContent, "");
  assert.equal($("request-id").textContent, "—");
  send("Fresh question");
  await until(() => !$("send").disabled);
  assert.equal(requests[2].messages.length, 1);
});

test("failed requests preserve the draft and exclude failed turns from history", async (t) => {
  const {$, send, requests} = await fixture(t, (_, count) => count === 1
    ? new Response(JSON.stringify({error: "Application rate limit reached", retry_after: 60, request_id: "failure-id"}), {status: 429})
    : reply());
  send("Retry this");
  await until(() => !$("send").disabled);
  assert.equal($("prompt").value, "Retry this");
  assert.equal($("request-id").textContent, "failure-id");
  assert.equal($("retry-after").textContent, "60 seconds");
  assert.equal($("error").hidden, false);
  assert.equal($("messages").children.length, 0);
  send("Retry this");
  await until(() => !$("send").disabled);
  assert.equal(requests[1].messages.length, 1);
  assert.equal($("error").hidden, true);
});

test("pending inference prevents duplicate sends and unknown counts remain unknown", async (t) => {
  let finish;
  const {$, send, requests} = await fixture(t, () => new Promise((resolve) => { finish = resolve; }));
  send("One question");
  assert.equal($("clear").disabled, true);
  send("Duplicate");
  assert.equal(requests.length, 1);
  finish(new Response(JSON.stringify({content: "Answer", model: "ollama:sample", usage: {prompt_tokens: null, completion_tokens: null, total_tokens: null}, request_id: null, latency_ms: 1})));
  await until(() => !$("send").disabled);
  assert.equal($("total-tokens").textContent, "Unknown");
});


test("streamed text is rendered safely and final usage updates the details", async (t) => {
  const event = (value) => `data: ${JSON.stringify(value)}\n\n`;
  const data = event({model: "ollama:sample", choices: [{delta: {content: "<script>text</script>"}}]}) + event({choices: [], usage: {prompt_tokens: 3, completion_tokens: 2, total_tokens: 5}}) + "data: [DONE]\n\n";
  const {$, send, requests} = await fixture(t, () => new Response(data, {headers: {"x-request-id": "stream-request"}}));
  $("streaming").checked = true;
  send("Synthetic stream");
  await until(() => !$("send").disabled);
  assert.equal($("total-tokens").textContent, "5");
  assert.equal($("request-id").textContent, "stream-request");
  assert.equal($("cache-status").textContent, "BYPASS");
  assert.equal($("messages").querySelectorAll("script").length, 0);
  assert.match($("messages").textContent, /<script>text/);
  send("Follow-up");
  await until(() => !$("send").disabled);
  assert.equal(requests[1].messages.length, 3);
});

test("Stop aborts the pending request and preserves the draft", async (t) => {
  let aborted = false;
  const {$, send} = await fixture(t, (_, count, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener("abort", () => { aborted = true; reject(new DOMException("Stopped", "AbortError")); });
  }));
  send("Stop this request");
  $("stop").click();
  await until(() => !$("send").disabled);
  assert.ok(aborted);
  assert.equal($("prompt").value, "Stop this request");
  assert.match($("error").textContent, /Request stopped/);
  assert.equal($("stop").hidden, true);
});

test("terminal stream failure keeps partial text out of the next request history", async (t) => {
  const initial = 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n';
  const {$, send, requests} = await fixture(t, (_, count) => count === 1
    ? new Response(initial + 'event: error\ndata: {"error":{"message":"Safe failure"}}\n\n') : reply());
  $("streaming").checked = true;
  send("Retry stream");
  await until(() => !$("send").disabled);
  assert.match($("messages").textContent, /Partial response/);
  assert.equal($("prompt").value, "Retry stream");
  $("streaming").checked = false;
  send("Retry stream");
  await until(() => !$("send").disabled);
  assert.equal(requests[1].messages.length, 1);
});


test("Stop after a streamed delta keeps partial output visible and excludes it from history", async (t) => {
  const {$, send, requests} = await fixture(t, (_, count, options) => {
    if (count > 1) return reply();
    const body = new ReadableStream({start(sink) {
      sink.enqueue(new TextEncoder().encode('data: {"choices":[{"delta":{"content":"partial text"}}]}\n\n'));
      options.signal.addEventListener("abort", () => sink.error(new DOMException("Stopped", "AbortError")));
    }});
    return new Response(body, {headers: {"x-request-id": "cancelled-stream"}});
  });
  $("streaming").checked = true;
  send("Question to stop");
  await until(() => $("messages").textContent.includes("partial text"));
  assert.equal($("send").disabled, true);
  $("stop").click();
  await until(() => !$("send").disabled);
  assert.match($("messages").textContent, /Partial response/);
  assert.equal($("request-id").textContent, "cancelled-stream");
  assert.equal($("prompt").value, "Question to stop");
  $("streaming").checked = false;
  send("Question to stop");
  await until(() => !$("send").disabled);
  assert.equal(requests[1].messages.length, 1);
});
