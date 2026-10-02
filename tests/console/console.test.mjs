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
    if (url.pathname.endsWith("/overview")) return response({requests: 1, total_tokens: 13, prompt_tokens: 8, completion_tokens: 5, cache_hits: 0, errors: 0, usage_unknown: 0, average_latency_ms: 12});
    if (url.pathname.endsWith("/usage")) return response({series: [{bucket: "2026-10-02T12:00:00Z", requests: 1, total_tokens: 13}], by_app: [{app_id: "sample-app", requests: 1, prompt_tokens: 8, completion_tokens: 5, errors: 0}], by_model: [{model: "ollama:small", requests: 1, prompt_tokens: 8, completion_tokens: 5, errors: 0}]});
    if (url.pathname.endsWith("/logs")) return response({items: [event]});
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
