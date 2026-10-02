import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {setTimeout as delay} from "node:timers/promises";
import test from "node:test";
import {JSDOM} from "jsdom";

const root = new URL("../../", import.meta.url);
const html = readFileSync(new URL("src/m87_gateway/control/static/index.html", root), "utf8");
const script = readFileSync(new URL("src/m87_gateway/control/static/app.js", root), "utf8");
const css = readFileSync(new URL("src/m87_gateway/control/static/styles.css", root), "utf8");

async function until(predicate) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (predicate()) return;
    await delay(5);
  }
  assert.fail("Console interaction did not complete");
}

async function consoleFixture(t) {
  const dom = new JSDOM(html, {url: "http://gateway/admin", runScripts: "outside-only"});
  t.after(async () => { await delay(20); dom.window.close(); });
  const {window} = dom;
  const style = window.document.createElement("style"); style.textContent = css; window.document.head.append(style);
  assert.ok(style.sheet.cssRules.length > 0);
  window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  window.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  window.URL.createObjectURL = () => "blob:fixture";
  window.URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = () => {};
  const projects = [{project_id: "default", name: "Default project", app_count: 0},
    {project_id: "alpha", name: "Alpha", app_count: 1}];
  const apps = [{app_id: "sample-app", project_id: "alpha", key_prefix: "fixture", allowed_models: ["auto"], capture_content: false, rate_limit_per_minute: null}];
  const event = {request_id: "fixture-request", created_at: "2026-10-02T12:00:00Z", project_id: "alpha", app_id: "sample-app", routed_model: "ollama:small", status_code: 200, total_tokens: 13, latency_ms: 12, cache_status: "disabled", provider_attempts: 1};
  let controls = {cache: {enabled: false, ttl_seconds: 300, max_entries: 1000}, retry: {max_attempts: 1, backoff_ms: 100}, limits: {max_concurrent_requests: 64}, max_request_bytes: 262144, max_message_chars: 65536, retention_days: 30, max_content_chars: 16384};
  const requests = [];
  let pendingChat = null;
  let deferredChat = false;
  let deferredDetail = false;
  let pendingDetail = null;
  const response = (value, status = 200, headers = {}) => new Response(status === 204 ? null : JSON.stringify(value), {status, headers: {"Content-Type": "application/json", ...headers}});
  window.fetch = async (input, options = {}) => {
    const url = new URL(input, "http://gateway");
    const method = options.method || "GET";
    const body = options.body ? JSON.parse(options.body) : null;
    requests.push({path: url.pathname, query: url.searchParams, method, body, headers: options.headers, signal: options.signal});
    if (url.pathname === "/v1/chat/completions") {
      if (deferredChat) return new Promise((resolve, reject) => {
        pendingChat = {resolve, reject};
        options.signal.addEventListener("abort", () => reject(new window.DOMException("Stopped", "AbortError")), {once: true});
      });
      return response({model: "ollama:small", choices: [{message: {content: "synthetic answer"}}], usage: {prompt_tokens: 8, completion_tokens: 5, total_tokens: 13}}, 200, {"X-Request-ID": "fixture-request"});
    }
    assert.equal(options.headers.Authorization, "Bearer synthetic-admin-key");
    if (url.pathname.endsWith("/controls")) { if (method === "PUT") { controls = body; return response(null, 204); } return response(controls); }
    if (url.pathname.endsWith("/diagnostics")) return response({ready: true, default_model: "ollama:small", active_requests: 0, checks: [{name: "Default provider", ok: true}]});
    if (url.pathname.endsWith("/cache/clear")) return response(null, 204);
    if (url.pathname.endsWith("/limits")) { Object.assign(apps[0], body); return response(null, 204); }
    if (url.pathname.endsWith("/setup")) return response({default_model: "ollama:small", capture_content: false, connections: [{provider: "ollama", label: "Ollama", configured: true, config: {base_url: "http://localhost:11434", timeout_seconds: 60, enabled: true}}]});
    if (url.pathname.endsWith("/projects")) {
      if (method === "POST") { projects.push({...body, app_count: 0}); return response(body, 201); }
      return response({items: projects});
    }
    if (url.pathname.endsWith("/apps")) {
      if (method === "POST") { apps.push({...body, key_prefix: "new-prefix"}); return response({...body, api_key: "m87_synthetic-key-shown-once"}, 201); }
      return response({items: apps});
    }
    if (url.pathname.endsWith("/project")) { apps[0].project_id = body.project_id; return response(null, 204); }
    if (url.pathname.includes("/apps/") && url.pathname.endsWith("/models")) { apps[0].allowed_models = body.allowed_models; return response(null, 204); }
    if (url.pathname.endsWith("/overview")) return response({requests: 1, total_tokens: 13, prompt_tokens: 8, completion_tokens: 5, cache_hits: 0, errors: 0, usage_unknown: 0, average_latency_ms: 12});
    if (url.pathname.endsWith("/usage")) return response({series: [{bucket: "2026-10-02T12:00:00Z", requests: 1, total_tokens: 13}], by_app: [{app_id: "sample-app", requests: 1, prompt_tokens: 8, completion_tokens: 5, errors: 0}], by_model: [{model: "ollama:small", requests: 1, prompt_tokens: 8, completion_tokens: 5, errors: 0}]});
    if (url.pathname.endsWith("/logs")) return method === "DELETE" ? response({deleted: 1}) : response({items: [event]});
    if (url.pathname.endsWith("/logs/export")) return response([event]);
    if (url.pathname.endsWith("/logs/fixture-request")) {
      if (deferredDetail) return new Promise((resolve) => { pendingDetail = () => resolve(response(event)); });
      return response(event);
    }
    assert.fail(`Unexpected console endpoint: ${url.pathname}`);
  };
  window.eval(script);
  const $ = (id) => window.document.getElementById(id);
  const submit = (id) => $(id).dispatchEvent(new window.Event("submit", {bubbles: true, cancelable: true}));
  $("admin-key").value = "synthetic-admin-key";
  submit("login-form");
  await until(() => !$("console").hidden);
  return {window, $, submit, requests, deferChat: () => { deferredChat = true; }, pending: () => pendingChat,
    deferDetail: () => { deferredDetail = true; }, detailPending: () => pendingDetail};
}

test("project selection scopes dashboard, usage, logs and export and renders charts", async (t) => {
  const {$, window, requests} = await consoleFixture(t);
  assert.equal($("token-chart").querySelectorAll("svg rect").length, 1);
  assert.match($("usage-apps").textContent, /sample-app/);
  $("project-filter").value = "alpha";
  $("project-filter").dispatchEvent(new window.Event("change"));
  await until(() => requests.some((item) => item.path.endsWith("/usage") && item.query.get("project_id") === "alpha"));
  window.document.querySelector('[data-view="logs"]').click();
  await until(() => requests.some((item) => item.query.get("limit") === "250" && item.query.get("project_id") === "alpha"));
  $("export").dispatchEvent(new window.MouseEvent("click", {bubbles: true, cancelable: true}));
  await until(() => requests.some((item) => item.path.endsWith("/export")));
  assert.equal(requests.find((item) => item.path.endsWith("/export")).query.get("project_id"), "alpha");
});

test("project creation and application creation submit selected membership", async (t) => {
  const {$, window, submit, requests} = await consoleFixture(t);
  window.document.querySelector('[data-view="projects"]').click();
  $("project-form").elements.project_id.value = "beta";
  $("project-form").elements.name.value = "Beta";
  submit("project-form");
  await until(() => $("app-project").value === "beta");
  $("app-form").elements.app_id.value = "new-app";
  submit("app-form");
  await until(() => !$("new-key").hidden);
  const request = requests.find((item) => item.path.endsWith("/apps") && item.method === "POST");
  assert.equal(request.body.project_id, "beta");
  assert.match($("new-key").textContent, /m87_synthetic-key-shown-once/);
});

test("application selector sends an explicit project assignment", async (t) => {
  const {$, window, requests} = await consoleFixture(t);
  window.document.querySelector('[data-view="apps"]').click();
  await until(() => $("apps").querySelector("select"));
  const selection = $("apps").querySelector("select");
  selection.value = "default";
  selection.dispatchEvent(new window.Event("change"));
  await until(() => requests.some((item) => item.method === "PATCH"));
  assert.equal(requests.find((item) => item.method === "PATCH").body.project_id, "default");
});

test("content capture is configured at gateway level without per-app controls", async (t) => {
  const {$, submit, requests} = await consoleFixture(t);
  assert.equal($("app-form").querySelector('[name="capture_content"]'), null);
  $("setup-form").elements.capture_content.checked = true;
  submit("setup-form");
  await until(() => requests.some((item) => item.path.endsWith("/setup") && item.method === "PUT"));
  assert.equal(requests.find((item) => item.path.endsWith("/setup") && item.method === "PUT").body.capture_content, true);
});

test("application model permissions save without creating or revoking a key", async (t) => {
  const {$, window, requests} = await consoleFixture(t);
  window.document.querySelector('[data-view="apps"]').click();
  await until(() => $("apps").querySelector('input[aria-label="Allowed models for sample-app"]'));
  $("apps").querySelector("input").value = "auto, ollama:gemma3:1b";
  [...$("apps").querySelectorAll("button")].find((button) => button.textContent === "Save models").click();
  await until(() => requests.some((item) => item.path.endsWith("/models")));
  const update = requests.find((item) => item.path.endsWith("/models"));
  assert.equal(update.method, "PATCH");
  assert.deepEqual(update.body.allowed_models, ["auto", "ollama:gemma3:1b"]);
  assert.equal(requests.some((item) => item.method === "DELETE" || item.method === "POST"), false);
});

test("API tester uses app credentials and shows a correlated result", async (t) => {
  const {$, submit, requests} = await consoleFixture(t);
  $("tester-form").elements.app_key.value = "synthetic-app-key";
  $("tester-form").elements.prompt.value = "synthetic prompt";
  $("tester-form").elements.max_tokens.value = "32";
  submit("tester-form");
  await until(() => $("tester-result").textContent.includes("synthetic answer"));
  const request = requests.find((item) => item.path === "/v1/chat/completions");
  assert.equal(request.headers.Authorization, "Bearer synthetic-app-key");
  assert.equal(request.headers["X-Project-ID"], undefined);
  assert.equal(request.body.max_tokens, 32);
  assert.equal($("tester-form").elements.app_key.value, "");
  assert.match($("tester-status").textContent, /fixture-request/);
  $("tester-detail").click();
  await until(() => $("detail").hasAttribute("open"));
  assert.match($("detail-body").textContent, /alpha/);
});

test("locking clears tester content and aborts a pending test", async (t) => {
  const fixture = await consoleFixture(t);
  const {$, submit, deferChat, pending} = fixture;
  deferChat();
  $("tester-form").elements.app_key.value = "synthetic-app-key";
  $("tester-form").elements.prompt.value = "private synthetic marker";
  submit("tester-form");
  await until(pending);
  $("lock").click();
  assert.equal($("tester-form").elements.prompt.value, "");
  assert.equal($("tester-result").textContent, "");
  assert.equal($("console").hidden, true);
  await until(() => !$("tester-form").querySelector("button").disabled);
  assert.equal($("tester-status").textContent, "No request sent.");
});

test("an exchange response arriving after lock cannot reopen its detail", async (t) => {
  const {$, window, deferDetail, detailPending} = await consoleFixture(t);
  deferDetail();
  window.document.querySelector('[data-view="logs"]').click();
  await until(() => $("logs").querySelector("tr[data-id]"));
  $("logs").querySelector("tr[data-id]").click();
  await until(detailPending);
  $("lock").click();
  detailPending()();
  await delay(10);
  assert.equal($("detail").hasAttribute("open"), false);
  assert.equal($("detail-body").textContent, "");
});


test("controls edit persistent values and show readiness, then clear response cache", async (t) => {
  const {$, window, submit, requests} = await consoleFixture(t);
  window.document.querySelector('[data-view="controls"]').click();
  await until(() => $("controls-form").elements.retention_days.value === "30");
  assert.match($("readiness-status").textContent, /Ready/);
  const form = $("controls-form");
  form.elements.max_concurrent_requests.value = "8";
  form.elements.max_attempts.value = "2";
  form.elements.retention_days.value = "90";
  form.elements.cache_enabled.checked = true;
  submit("controls-form");
  await until(() => requests.some((r) => r.path.endsWith("/controls") && r.method === "PUT"));
  const request = requests.find((r) => r.path.endsWith("/controls") && r.method === "PUT");
  assert.equal(request.body.limits.max_concurrent_requests, 8);
  assert.equal(request.body.retry.max_attempts, 2);
  assert.equal(request.body.retention_days, 90);
  assert.equal(request.body.cache.enabled, true);
  $("clear-cache").click();
  await until(() => requests.some((r) => r.path.endsWith("/cache/clear")));
});

test("application limits edit without replacing its key", async (t) => {
  const {$, window, requests} = await consoleFixture(t);
  window.document.querySelector('[data-view="apps"]').click();
  await until(() => $("apps").querySelector('input[aria-label="Requests per minute for sample-app"]'));
  $("apps").querySelector('input[aria-label="Requests per minute for sample-app"]').value = "5";
  $("apps").querySelector('input[aria-label="Concurrent requests for sample-app"]').value = "2";
  [...$("apps").querySelectorAll("button")].find((b) => b.textContent === "Save limits").click();
  await until(() => requests.some((r) => r.path.endsWith("/limits")));
  const request = requests.find((r) => r.path.endsWith("/limits"));
  assert.deepEqual(request.body, {rate_limit_per_minute: 5, max_concurrent_requests: 2});
  assert.equal(request.method, "PATCH");
});

test("log deletion requires confirmation and follows selected project", async (t) => {
  const {$, window, requests} = await consoleFixture(t);
  $("project-filter").value = "alpha";
  $("project-filter").dispatchEvent(new window.Event("change"));
  window.document.querySelector('[data-view="logs"]').click();
  window.confirm = () => false;
  $("delete-logs").click();
  assert.equal(requests.some((r) => r.method === "DELETE"), false);
  window.confirm = (message) => { assert.match(message, /project alpha/); return true; };
  $("delete-logs").click();
  await until(() => requests.some((r) => r.method === "DELETE"));
  const deletion = requests.find((r) => r.method === "DELETE");
  assert.deepEqual(deletion.body, {confirmation: "DELETE", project_id: "alpha"});
});
