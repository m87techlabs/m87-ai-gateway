let adminKey = "";
let activeView = "overview";
let connections = [];
let projects = [];
let activeProject = "";
let activeKeyApp = "";
let appKeysGeneration = 0;
let sessionGeneration = 0;
let testerRequestId = "";
let testerController = null;
let connectionTestGeneration = 0;
const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const headers = {...(options.headers || {}), Authorization: `Bearer ${adminKey}`};
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(`/admin/api${path}`, {...options, headers, cache: "no-store"});
  if (!response.ok) {
    let message = "Request failed";
    try { message = (await response.json()).error.message; } catch (_) {}
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response;
}

function empty(target, message = "No records yet.") {
  target.replaceChildren();
  const node = document.createElement("p");
  node.className = "empty";
  node.textContent = message;
  target.append(node);
}

function cell(row, value) {
  const td = document.createElement("td");
  td.textContent = value ?? "—";
  row.append(td);
  return td;
}

function table(target, headings, rows, render) {
  if (!rows.length) return empty(target);
  const element = document.createElement("table");
  const head = document.createElement("thead");
  const header = document.createElement("tr");
  headings.forEach((label) => { const th = document.createElement("th"); th.textContent = label; header.append(th); });
  head.append(header);
  const body = document.createElement("tbody");
  rows.forEach((item) => { const row = document.createElement("tr"); render(row, item); body.append(row); });
  element.append(head, body);
  target.replaceChildren(element);
}

function notice(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  window.setTimeout(() => $("toast").classList.remove("show"), 2600);
}

function renderLogs(target, rows, limit) {
  table(target, ["Time", "Project", "App", "Model", "Status", "Tokens", "Latency", "Cache", "Attempts"], rows.slice(0, limit), (row, item) => {
    row.dataset.id = item.request_id;
    cell(row, new Date(item.created_at).toLocaleString());
    cell(row, item.project_id);
    cell(row, item.app_id);
    cell(row, item.routed_model || item.model);
    const status = cell(row, item.status_code);
    status.className = `status ${item.status_code >= 400 ? "error" : ""}`;
    cell(row, item.total_tokens);
    cell(row, item.latency_ms == null ? null : `${item.latency_ms} ms`);
    cell(row, item.cache_status || "disabled");
    cell(row, item.provider_attempts ?? 0);
    row.addEventListener("click", () => showDetail(item.request_id));
  });
}

async function loadOverview() {
  const scope = activeProject;
  const [summaryResponse, logsResponse, usageResponse] = await Promise.all([api(scoped("/overview")), api(scoped("/logs", {limit: 8})), api(scoped("/usage"))]);
  const summary = await summaryResponse.json();
  const logs = await logsResponse.json();
  const usage = await usageResponse.json();
  if (scope !== activeProject || !adminKey) return;
  $("requests").textContent = summary.requests.toLocaleString();
  $("tokens").textContent = summary.total_tokens.toLocaleString();
  $("errors").textContent = summary.errors.toLocaleString();
  $("latency").textContent = `${summary.average_latency_ms} ms`;
  $("input-tokens").textContent = summary.prompt_tokens.toLocaleString();
  $("output-tokens").textContent = summary.completion_tokens.toLocaleString();
  $("cache-hits").textContent = summary.cache_hits.toLocaleString();
  $("usage-unknown").textContent = summary.usage_unknown.toLocaleString();
  renderChart($("request-chart"), usage.series, "requests", "Hourly requests");
  renderChart($("token-chart"), usage.series, "total_tokens", "Hourly provider tokens");
  renderUsage($("usage-apps"), usage.by_app, "app_id", "Application");
  renderUsage($("usage-models"), usage.by_model, "model", "Model");
  renderLogs($("recent"), logs.items, 8);
}

async function loadLogs() {
  const scope = activeProject;
  $("delete-logs").textContent = scope ? "Delete selected project logs" : "Delete all logs";
  const response = await api(scoped("/logs", {limit: 250}));
  const data = await response.json();
  if (scope === activeProject && adminKey) renderLogs($("logs"), data.items, 250);
}

function scoped(path, values = {}) {
  const query = new URLSearchParams(values);
  if (activeProject) query.set("project_id", activeProject);
  return query.size ? `${path}?${query}` : path;
}

function renderUsage(target, rows, field, label) {
  table(target, [label, "Requests", "Input tokens", "Output tokens", "Errors"], rows, (row, item) => {
    cell(row, item[field] || "Unattributed"); cell(row, item.requests); cell(row, item.prompt_tokens); cell(row, item.completion_tokens); cell(row, item.errors);
  });
}

function renderChart(target, series, field, label) {
  if (!series.some((item) => item[field])) return empty(target, "No activity in this window.");
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", "0 0 720 150"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", label);
  const maximum = Math.max(1, ...series.map((item) => item[field]));
  const width = 720 / series.length;
  series.forEach((item, index) => {
    const rect = document.createElementNS(namespace, "rect");
    const height = item[field] / maximum * 135;
    rect.setAttribute("x", index * width + 2); rect.setAttribute("y", 140 - height);
    rect.setAttribute("width", Math.max(1, width - 4)); rect.setAttribute("height", height);
    rect.setAttribute("class", field === "requests" ? "requests-bar" : "tokens-bar");
    const title = document.createElementNS(namespace, "title"); title.textContent = `${item.bucket}: ${item[field]} ${field === "requests" ? "requests" : "reported tokens"}`;
    rect.append(title); svg.append(rect);
  });
  const caption = document.createElement("p"); caption.className = "muted";
  caption.textContent = `${series[0].bucket} → ${series.at(-1).bucket} · hover for counts`;
  target.replaceChildren(svg, caption);
}

async function loadProjectOptions() {
  projects = (await (await api("/projects")).json()).items;
  const appProject = $("app-project").value || activeProject || "default";
  $("project-filter").replaceChildren(); $("app-project").replaceChildren();
  const all = document.createElement("option"); all.value = ""; all.textContent = "All projects"; $("project-filter").append(all);
  projects.forEach((item) => {
    for (const id of ["project-filter", "app-project"]) {
      const option = document.createElement("option"); option.value = item.project_id; option.textContent = `${item.name} (${item.project_id})`; $(id).append(option);
    }
  });
  $("project-filter").value = activeProject;
  $("app-project").value = appProject;
}

async function loadProjects() {
  await loadProjectOptions();
  table($("projects"), ["Project", "Name", "Managed apps", ""], projects, (row, item) => {
    cell(row, item.project_id); cell(row, item.name); cell(row, item.app_count);
    const action = cell(row, ""); const button = document.createElement("button"); button.textContent = "View usage";
    button.addEventListener("click", () => { activeProject = item.project_id; $("project-filter").value = activeProject; document.querySelector('[data-view="overview"]').click(); }); action.append(button);
  });
}

async function showDetail(requestId) {
  const session = sessionGeneration;
  const response = await api(`/logs/${encodeURIComponent(requestId)}`);
  const item = await response.json();
  if (session !== sessionGeneration || !adminKey) return;
  const body = $("detail-body");
  body.replaceChildren();
  const grid = document.createElement("div");
  grid.className = "detail-grid";
  [["Request", item.request_id], ["Project", item.project_id], ["Application", item.app_id], ["Model", item.routed_model], ["Status", item.status_code], ["Tokens", item.total_tokens], ["Cache", item.cache_status], ["Attempts", item.provider_attempts], ["Error", item.error_type], ["Latency", `${item.latency_ms} ms`]].forEach(([label, value]) => {
    const box = document.createElement("div");
    const caption = document.createElement("span"); caption.textContent = label;
    const strong = document.createElement("strong"); strong.textContent = value ?? "—";
    box.append(caption, strong); grid.append(box);
  });
  body.append(grid);
  [["LLM input", item.request_content], ["LLM output", item.response_content]].forEach(([label, value]) => {
    const title = document.createElement("h3"); title.textContent = label;
    const pre = document.createElement("pre"); pre.textContent = value == null ? "Content was not recorded for this exchange. Gateway capture applies to new requests." : JSON.stringify(value, null, 2);
    body.append(title, pre);
    const truncated = label === "LLM input" ? item.request_content_truncated : item.response_content_truncated;
    if (truncated) { const note = document.createElement("p"); note.className = "muted"; note.textContent = "Content was truncated at the configured capture limit."; body.append(note); }
  });
  $("detail").showModal();
}

async function loadApps() {
  const [response] = await Promise.all([api("/apps"), loadProjectOptions()]);
  table($("apps"), ["Application", "Project", "Key prefix", "Models", "Limits", ""], (await response.json()).items, (row, item) => {
    cell(row, item.app_id);
    const projectCell = cell(row, ""); const selection = document.createElement("select"); selection.setAttribute("aria-label", `Project for ${item.app_id}`);
    projects.forEach((project) => { const option = document.createElement("option"); option.value = project.project_id; option.textContent = project.name; selection.append(option); });
    selection.value = item.project_id; projectCell.append(selection);
    selection.addEventListener("change", async () => {
      try { await api(`/apps/${encodeURIComponent(item.app_id)}/project`, {method: "PATCH", body: JSON.stringify({project_id: selection.value})}); notice("Project changed for future requests"); item.project_id = selection.value; }
      catch (error) { selection.value = item.project_id; notice(error.message); }
    });
    cell(row, `${item.key_prefix || "No active key"}${item.key_prefix ? "…" : ""} (${item.active_key_count ?? 1} active)`);
    const modelCell = cell(row, ""); const models = document.createElement("input"); models.value = item.allowed_models.join(", "); models.setAttribute("aria-label", `Allowed models for ${item.app_id}`);
    const saveModels = document.createElement("button"); saveModels.type = "button"; saveModels.textContent = "Save models";
    saveModels.addEventListener("click", async () => {
      saveModels.disabled = models.disabled = true;
      try {
        const allowed = models.value.split(",").map((value) => value.trim()).filter(Boolean);
        await api(`/apps/${encodeURIComponent(item.app_id)}/models`, {method: "PATCH", body: JSON.stringify({allowed_models: allowed})});
        item.allowed_models = allowed; notice("Model permissions saved; application key unchanged");
      } catch (error) { notice(error.message); }
      finally { saveModels.disabled = models.disabled = false; }
    });
    modelCell.append(models, saveModels);
    const limitCell = cell(row, "");
    const rpm = document.createElement("input"); rpm.type = "number"; rpm.min = "1"; rpm.max = "100000"; rpm.placeholder = "Unlimited RPM"; rpm.value = item.rate_limit_per_minute ?? ""; rpm.setAttribute("aria-label", `Requests per minute for ${item.app_id}`);
    const concurrent = document.createElement("input"); concurrent.type = "number"; concurrent.min = "1"; concurrent.max = "10000"; concurrent.placeholder = "Gateway concurrency limit"; concurrent.value = item.max_concurrent_requests ?? ""; concurrent.setAttribute("aria-label", `Concurrent requests for ${item.app_id}`);
    const saveLimits = document.createElement("button"); saveLimits.type = "button"; saveLimits.textContent = "Save limits";
    saveLimits.addEventListener("click", async () => {
      if (!rpm.reportValidity() || !concurrent.reportValidity()) return;
      saveLimits.disabled = true;
      try {
        await api(`/apps/${encodeURIComponent(item.app_id)}/limits`, {method: "PATCH", body: JSON.stringify({rate_limit_per_minute: rpm.value ? Number(rpm.value) : null, max_concurrent_requests: concurrent.value ? Number(concurrent.value) : null})});
        notice("Limits saved; application key unchanged. Existing rate windows and active requests remain.");
      } catch (error) { notice(error.message); }
      finally { saveLimits.disabled = false; }
    });
    limitCell.append(rpm, concurrent, saveLimits);
    const action = cell(row, ""); const button = document.createElement("button"); button.className = "danger"; button.textContent = "Delete application";
    button.addEventListener("click", async () => {
      if (!window.confirm(`Delete application ${item.app_id} and revoke all of its keys? Logs and usage remain.`)) return;
      try {
        await api(`/apps/${encodeURIComponent(item.app_id)}`, {method: "DELETE"});
        if (activeKeyApp === item.app_id) { activeKeyApp = ""; appKeysGeneration += 1; $("app-keys-panel").hidden = true; $("replacement-key").replaceChildren(); }
        notice("Application deleted and keys revoked"); await loadApps();
      } catch (error) { notice(error.message); }
    });
    const manage = document.createElement("button"); manage.type = "button"; manage.textContent = "Manage keys";
    manage.addEventListener("click", async () => {
      $("replacement-key").replaceChildren(); $("replacement-key").hidden = true;
      try { await loadAppKeys(item.app_id); } catch (error) { notice(error.message); }
    });
    action.append(manage, button);
  });
}

async function loadAppKeys(appId) {
  const session = sessionGeneration; const generation = ++appKeysGeneration; activeKeyApp = appId;
  $("app-keys-panel").hidden = true;
  const response = await api(`/apps/${encodeURIComponent(appId)}/keys`); const data = await response.json();
  if (session !== sessionGeneration || generation !== appKeysGeneration || !adminKey) return;
  $("app-keys-title").textContent = `Keys for ${appId}`; $("app-keys-panel").hidden = false;
  table($("application-keys"), ["Prefix", "Created", "Expires", "Status", ""], data.items, (row, item) => {
    cell(row, `${item.key_prefix}…`); cell(row, item.created_at); cell(row, item.expires_at || "No expiry");
    cell(row, item.revoked_at ? "Revoked" : item.active ? "Active" : "Expired");
    const action = cell(row, ""); const revoke = document.createElement("button"); revoke.type = "button"; revoke.className = "danger"; revoke.textContent = "Revoke key"; revoke.disabled = !item.active;
    revoke.addEventListener("click", async () => {
      if (!window.confirm(`Revoke key ${item.key_prefix} for ${appId}? Update callers first.`)) return;
      revoke.disabled = true;
      try { await api(`/apps/${encodeURIComponent(appId)}/keys/${encodeURIComponent(item.key_id)}`, {method: "DELETE"}); if (session !== sessionGeneration || !adminKey) return; notice("Key revoked"); await loadApps(); await loadAppKeys(appId); }
      catch (error) { notice(error.message); revoke.disabled = false; }
    });
    action.append(revoke);
  });
}

async function loadManagementAudit() {
  const session = sessionGeneration; const scope = activeProject;
  const response = await api(scoped("/management-events", {limit: 250})); const data = await response.json();
  if (session !== sessionGeneration || scope !== activeProject || !adminKey) return;
  table($("management-events"), ["Time", "Actor", "Action", "Project", "Application", "Key ID"], data.items, (row, item) => {
    for (const field of ["created_at", "actor", "action", "project_id", "app_id", "key_id"]) cell(row, item[field]);
  });
}

async function loadProviderKeys() {
  const response = await api("/provider-keys");
  table($("provider-keys"), ["Provider", "Alias", "Updated", ""], (await response.json()).items, (row, item) => {
    cell(row, item.provider); cell(row, item.alias); cell(row, new Date(item.updated_at).toLocaleString());
    const action = cell(row, ""); const button = document.createElement("button"); button.className = "danger"; button.textContent = "Remove";
    button.addEventListener("click", async () => { await api(`/provider-keys/${encodeURIComponent(item.provider)}/${encodeURIComponent(item.alias)}`, {method: "DELETE"}); notice("Provider key removed"); await loadProviderKeys(); });
    action.append(button);
  });
}

async function loadDestinations() {
  const response = await api("/destinations");
  table($("destinations"), ["Destination", "Data", "Target", "Status"], (await response.json()).items, (row, item) => {
    cell(row, item.name); cell(row, item.type); cell(row, item.target); const status = cell(row, item.enabled ? "Enabled" : "Disabled"); status.className = item.enabled ? "enabled" : "disabled";
  });
}

function fillConnection() {
  connectionTestGeneration++;
  const item = connections.find((item) => item.provider === $("connection-provider").value);
  if (!item) return;
  const form = $("connection-form");
  form.elements.base_url.value = item.config.base_url || "";
  form.elements.timeout_seconds.value = item.config.timeout_seconds;
  form.elements.enabled.checked = item.config.enabled;
  form.elements.key.value = "";
  form.elements.clear_key.checked = false;
  $("connection-test-status").textContent = "Test the endpoint above without saving it. No completion is generated.";
  $("connection-test-status").className = "muted";
  $("discovered-models").textContent = item.has_stored_key ? "Provider key stored. Discover models to test this connection." : "Discover models after saving this connection.";
}

async function loadSetup() {
  const data = await (await api("/setup")).json();
  connections = data.connections;
  const selected = $("connection-provider").value;
  for (const id of ["connection-provider", "key-provider"]) {
    $(id).replaceChildren();
    connections.forEach((item) => {
      const option = document.createElement("option"); option.value = item.provider; option.textContent = item.label; $(id).append(option);
    });
  }
  if (connections.some((item) => item.provider === selected)) $("connection-provider").value = selected;
  else $("connection-provider").value = "ollama";
  fillConnection();
  $("setup-form").elements.default_model.value = data.default_model;
  $("setup-form").elements.capture_content.checked = data.capture_content;
  $("app-form").elements.allowed_models.value = `auto,${data.default_model}`;
  $("integration-example").textContent = JSON.stringify({url: `${window.location.origin}/v1/chat/completions`, authorization: "Bearer <application-key>", body: {model: data.default_model, messages: [{role: "user", content: "Hello"}]}}, null, 2);
  return data;
}

async function loadControls() {
  const session = sessionGeneration;
  const [values, report] = await Promise.all([api("/controls").then((r) => r.json()), api("/diagnostics").then((r) => r.json())]);
  if (session !== sessionGeneration || !adminKey) return;
  const fields = {...values, ...values.cache, ...values.retry, ...values.limits};
  const form = $("controls-form");
  for (const name of ["max_concurrent_requests", "max_request_bytes", "max_message_chars", "max_attempts", "backoff_ms", "ttl_seconds", "max_entries", "retention_days", "max_content_chars"]) form.elements[name].value = fields[name];
  form.elements.cache_enabled.checked = values.cache.enabled;
  $("readiness-status").textContent = `${report.ready ? "Ready" : "Needs configuration"} · ${report.default_model} · ${report.active_requests} active requests`;
  table($("readiness-checks"), ["Check", "Status", "Action"], report.checks, (row, item) => { cell(row, item.name); cell(row, item.ok ? "OK" : "Needs attention"); cell(row, item.ok ? "—" : item.message); });
}

const loaders = {audit: loadManagementAudit, setup: loadSetup, controls: loadControls, projects: loadProjects, tester: async () => {}, overview: loadOverview, logs: loadLogs, apps: loadApps, keys: loadProviderKeys, destinations: loadDestinations};

async function refresh() {
  try { await loaders[activeView](); } catch (error) { notice(error.message); }
}

document.querySelectorAll(".nav").forEach((button) => button.addEventListener("click", async () => {
  document.querySelectorAll(".nav").forEach((node) => node.classList.remove("active"));
  document.querySelectorAll(".view").forEach((node) => { node.hidden = true; });
  button.classList.add("active"); activeView = button.dataset.view;
  $(`view-${activeView}`).hidden = false;
  $("view-title").textContent = button.textContent;
  await refresh();
}));

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault(); sessionGeneration += 1; adminKey = $("admin-key").value;
  try {
    const setup = await loadSetup(); await loadProjectOptions(); await loadOverview(); $("admin-key").value = ""; $("login").hidden = true; $("console").hidden = false; $("login-error").textContent = "";
    if (!setup.connections.some((item) => item.configured)) document.querySelector('[data-view="setup"]').click();
  } catch (error) { adminKey = ""; $("login-error").textContent = error.message; }
});

$("lock").addEventListener("click", () => { sessionGeneration += 1; appKeysGeneration += 1; activeKeyApp = ""; $("app-keys-panel").hidden = true; $("application-keys").replaceChildren(); $("replacement-key").replaceChildren(); $("replacement-key").hidden = true; $("management-events").replaceChildren(); adminKey = ""; testerController?.abort(); $("console").hidden = true; $("login").hidden = false; $("new-key").replaceChildren(); $("detail-body").replaceChildren(); $("detail").close(); $("tester-result").replaceChildren(); $("tester-form").elements.prompt.value = ""; testerRequestId = ""; $("tester-detail").hidden = true; $("tester-status").textContent = "No request sent."; document.querySelectorAll('input[type="password"]').forEach((node) => { node.value = ""; }); });
$("refresh").addEventListener("click", refresh);
$("close-detail").addEventListener("click", () => $("detail").close());

$("app-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = new FormData(event.currentTarget); const session = sessionGeneration;
  const payload = {app_id: form.get("app_id"), project_id: form.get("project_id"), allowed_models: form.get("allowed_models").split(",").map((value) => value.trim()).filter(Boolean)};
  if (form.get("rate_limit_per_minute")) payload.rate_limit_per_minute = Number(form.get("rate_limit_per_minute"));
  if (form.get("max_concurrent_requests")) payload.max_concurrent_requests = Number(form.get("max_concurrent_requests"));
  try {
    const response = await api("/apps", {method: "POST", body: JSON.stringify(payload)}); const item = await response.json();
    if (session !== sessionGeneration || !adminKey) return;
    $("new-key").hidden = false; $("new-key").textContent = `Copy now — shown once: ${item.api_key}`; notice("Application key created"); await loadApps();
  } catch (error) { notice(error.message); }
});

$("app-key-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const element = event.currentTarget;
  if (!activeKeyApp || !element.reportValidity()) return;
  const session = sessionGeneration; const appId = activeKeyApp; const generation = appKeysGeneration;
  const form = new FormData(element); const payload = {revoke_existing: form.has("revoke_existing")};
  if (form.get("expires_in_days")) payload.expires_in_days = Number(form.get("expires_in_days"));
  if (payload.revoke_existing && !window.confirm(`Immediately revoke existing keys for ${appId}? Callers using them will be rejected.`)) return;
  const button = element.querySelector('button[type="submit"]'); button.disabled = true;
  $("replacement-key").replaceChildren(); $("replacement-key").hidden = true;
  try {
    const response = await api(`/apps/${encodeURIComponent(appId)}/keys`, {method: "POST", body: JSON.stringify(payload)}); const data = await response.json();
    if (session !== sessionGeneration || generation !== appKeysGeneration || !adminKey || appId !== activeKeyApp) return;
    $("replacement-key").textContent = `Copy now — shown once: ${data.api_key}`; $("replacement-key").hidden = false;
    element.elements.revoke_existing.checked = false; notice("Replacement key created"); await loadApps(); await loadAppKeys(appId);
  } catch (error) { if (session === sessionGeneration) notice(error.message); }
  finally { button.disabled = false; }
});

$("provider-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const element = event.currentTarget; const form = new FormData(element);
  try {
    await api("/provider-keys", {method: "PUT", body: JSON.stringify(Object.fromEntries(form))}); element.elements.key.value = ""; notice("Provider key stored"); await loadProviderKeys();
  } catch (error) { notice(error.message); }
});

$("connection-form").addEventListener("input", () => {
  connectionTestGeneration++;
  $("connection-test-status").textContent = "Settings changed. Test connection to check the current endpoint.";
  $("connection-test-status").className = "muted";
});
$("connection-provider").addEventListener("change", fillConnection);
$("connection-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const element = event.currentTarget; const form = new FormData(element);
  const payload = {config: {base_url: form.get("base_url"), timeout_seconds: Number(form.get("timeout_seconds")), enabled: form.has("enabled")}, clear_key: form.has("clear_key")};
  if (form.get("key")) payload.key = form.get("key");
  try {
    await api(`/connections/${encodeURIComponent(form.get("provider"))}`, {method: "PUT", body: JSON.stringify(payload)});
    element.elements.key.value = ""; notice("Connection saved"); await loadSetup();
  } catch (error) { notice(error.message); }
});
$("test-connection").addEventListener("click", async () => {
  const element = $("connection-form");
  if (!element.reportValidity()) return;
  const form = new FormData(element);
  const provider = form.get("provider");
  const session = sessionGeneration;
  const generation = connectionTestGeneration;
  const payload = {config: {base_url: form.get("base_url"), timeout_seconds: Number(form.get("timeout_seconds")), enabled: form.has("enabled")}, clear_key: form.has("clear_key")};
  if (form.get("key")) payload.key = form.get("key");
  const button = $("test-connection"); const status = $("connection-test-status");
  button.disabled = true; button.textContent = "Testing…";
  status.className = "muted"; status.textContent = "Checking connectivity from the gateway…";
  const current = () => generation === connectionTestGeneration && session === sessionGeneration && adminKey && $("connection-provider").value === provider && element.elements.base_url.value === payload.config.base_url;
  try {
    const data = await (await api(`/connections/${encodeURIComponent(provider)}/test`, {method: "POST", body: JSON.stringify(payload)})).json();
    if (!current()) return;
    status.className = data.ok ? "enabled" : "error";
    status.textContent = `${data.ok ? "Connected" : "Connection failed"}: ${data.message} (${data.latency_ms} ms)`;
  } catch (error) {
    if (current()) { status.className = "error"; status.textContent = `Connection failed: ${error.message}`; }
  } finally { button.disabled = false; button.textContent = "Test connection"; }
});
$("discover-models").addEventListener("click", async () => {
  try {
    const data = await (await api(`/connections/${encodeURIComponent($("connection-provider").value)}/models`)).json();
    $("discovered-models").textContent = data.items.length ? data.items.join("\n") : "Connected. No models reported; enter a model manually.";
    $("model-options").replaceChildren();
    data.items.forEach((name) => { const option = document.createElement("option"); option.value = name; $("model-options").append(option); });
    if (data.items.length) $("setup-form").elements.default_model.value = data.items[0];
  } catch (error) { $("discovered-models").textContent = error.message; }
});
$("setup-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  try {
    await api("/setup", {method: "PUT", body: JSON.stringify({default_model: form.get("default_model"), capture_content: form.has("capture_content")})});
    notice("Defaults saved. Create an application key next."); await loadSetup();
  } catch (error) { notice(error.message); }
});

$("export").addEventListener("click", async (event) => {
  event.preventDefault();
  try {
    const response = await api(scoped("/logs/export")); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "gateway-events.json"; link.click(); URL.revokeObjectURL(url);
  } catch (error) { notice(error.message); }
});

$("project-filter").addEventListener("change", () => { activeProject = $("project-filter").value; refresh(); });
$("project-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const element = event.currentTarget; const form = new FormData(element);
  try {
    await api("/projects", {method: "POST", body: JSON.stringify(Object.fromEntries(form))});
    notice("Project created. Assign an application next."); await loadProjects(); $("app-project").value = form.get("project_id"); element.reset();
  } catch (error) { notice(error.message); }
});
$("tester-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const element = event.currentTarget; const form = new FormData(element); const session = sessionGeneration;
  element.elements.app_key.value = ""; const button = element.querySelector('button[type="submit"]'); button.disabled = true;
  $("tester-status").textContent = "Waiting for the gateway…"; $("tester-result").replaceChildren(); $("tester-detail").hidden = true;
  const controller = new AbortController(); testerController = controller; const timeout = window.setTimeout(() => controller.abort(), 90000);
  const started = performance.now();
  try {
    const response = await fetch("/v1/chat/completions", {method: "POST", headers: {"Content-Type": "application/json", Authorization: `Bearer ${form.get("app_key")}`}, cache: "no-store", signal: controller.signal,
      body: JSON.stringify({model: form.get("model"), messages: [{role: "user", content: form.get("prompt")}], max_tokens: Number(form.get("max_tokens"))})});
    const data = await response.json();
    if (session !== sessionGeneration) return;
    testerRequestId = response.headers.get("X-Request-ID") || "";
    $("tester-status").textContent = `HTTP ${response.status} · ${Math.round(performance.now() - started)} ms · Request ${testerRequestId || "unavailable"}`;
    $("tester-result").textContent = JSON.stringify(data, null, 2); $("tester-detail").hidden = !testerRequestId;
  } catch (error) { if (session === sessionGeneration) $("tester-status").textContent = error.name === "AbortError" ? "Request stopped or timed out. Check logs for the outcome." : "The gateway could not be reached."; }
  finally { window.clearTimeout(timeout); if (testerController === controller) testerController = null; button.disabled = false; }
});
$("tester-detail").addEventListener("click", async () => {
  try { await showDetail(testerRequestId); } catch (error) { notice(`${error.message}. The audit write may still be finishing; retry shortly.`); }
});

$("controls-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = new FormData(event.currentTarget); const number = (name) => Number(form.get(name));
  const payload = {cache: {enabled: form.has("cache_enabled"), ttl_seconds: number("ttl_seconds"), max_entries: number("max_entries")}, retry: {max_attempts: number("max_attempts"), backoff_ms: number("backoff_ms")}, limits: {max_concurrent_requests: number("max_concurrent_requests")}, max_request_bytes: number("max_request_bytes"), max_message_chars: number("max_message_chars"), retention_days: number("retention_days"), max_content_chars: number("max_content_chars")};
  const button = event.currentTarget.querySelector('button[type="submit"]'); button.disabled = true;
  try { await api("/controls", {method: "PUT", body: JSON.stringify(payload)}); notice("Controls saved and response cache cleared"); await loadControls(); }
  catch (error) { notice(error.message); }
  finally { button.disabled = false; }
});
$("clear-cache").addEventListener("click", async () => {
  try { await api("/cache/clear", {method: "POST"}); notice("Response cache cleared"); }
  catch (error) { notice(error.message); }
});
$("delete-logs").addEventListener("click", async () => {
  const project = activeProject;
  const scope = project ? `project ${project}` : "ALL projects";
  if (!window.confirm(`Delete SQLite logs for ${scope}? Usage totals are preserved. Separate JSONL files and in-flight requests are unaffected.`)) return;
  try {
    const data = await (await api("/logs", {method: "DELETE", body: JSON.stringify({confirmation: "DELETE", project_id: project || null})})).json();
    notice(`${data.deleted} records deleted`); await loadLogs();
  } catch (error) { notice(error.message); }
});
