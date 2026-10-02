let adminKey = "";
let activeView = "overview";
let connections = [];
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
  table(target, ["Time", "App", "Model", "Status", "Tokens", "Latency", "Cache", "Attempts"], rows.slice(0, limit), (row, item) => {
    row.dataset.id = item.request_id;
    cell(row, new Date(item.created_at).toLocaleString());
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
  const [summaryResponse, logsResponse] = await Promise.all([api("/overview"), api("/logs?limit=8")]);
  const summary = await summaryResponse.json();
  const logs = await logsResponse.json();
  $("requests").textContent = summary.requests.toLocaleString();
  $("tokens").textContent = summary.total_tokens.toLocaleString();
  $("errors").textContent = summary.errors.toLocaleString();
  $("latency").textContent = `${summary.average_latency_ms} ms`;
  renderLogs($("recent"), logs.items, 8);
}

async function loadLogs() {
  const response = await api("/logs?limit=250");
  renderLogs($("logs"), (await response.json()).items, 250);
}

async function showDetail(requestId) {
  const response = await api(`/logs/${encodeURIComponent(requestId)}`);
  const item = await response.json();
  const body = $("detail-body");
  body.replaceChildren();
  const grid = document.createElement("div");
  grid.className = "detail-grid";
  [["Request", item.request_id], ["Application", item.app_id], ["Model", item.routed_model], ["Status", item.status_code], ["Tokens", item.total_tokens], ["Latency", `${item.latency_ms} ms`]].forEach(([label, value]) => {
    const box = document.createElement("div");
    const caption = document.createElement("span"); caption.textContent = label;
    const strong = document.createElement("strong"); strong.textContent = value ?? "—";
    box.append(caption, strong); grid.append(box);
  });
  body.append(grid);
  [["LLM input", item.request_content], ["LLM output", item.response_content]].forEach(([label, value]) => {
    const title = document.createElement("h3"); title.textContent = label;
    const pre = document.createElement("pre"); pre.textContent = value == null ? "Content capture was disabled for this exchange." : JSON.stringify(value, null, 2);
    body.append(title, pre);
  });
  $("detail").showModal();
}

async function loadApps() {
  const response = await api("/apps");
  table($("apps"), ["Application", "Key prefix", "Models", "RPM", "Content", ""], (await response.json()).items, (row, item) => {
    cell(row, item.app_id); cell(row, `${item.key_prefix}…`); cell(row, item.allowed_models.join(", ")); cell(row, item.rate_limit_per_minute || "Unlimited"); cell(row, item.capture_content ? "Enabled" : "Off");
    const action = cell(row, ""); const button = document.createElement("button"); button.className = "danger"; button.textContent = "Revoke";
    button.addEventListener("click", async () => { await api(`/apps/${encodeURIComponent(item.app_id)}`, {method: "DELETE"}); notice("Application key revoked"); await loadApps(); });
    action.append(button);
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
  const item = connections.find((item) => item.provider === $("connection-provider").value);
  if (!item) return;
  const form = $("connection-form");
  form.elements.base_url.value = item.config.base_url || "";
  form.elements.timeout_seconds.value = item.config.timeout_seconds;
  form.elements.enabled.checked = item.config.enabled;
  form.elements.key.value = "";
  form.elements.clear_key.checked = false;
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

const loaders = {setup: loadSetup, overview: loadOverview, logs: loadLogs, apps: loadApps, keys: loadProviderKeys, destinations: loadDestinations};

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
  event.preventDefault(); adminKey = $("admin-key").value;
  try {
    const setup = await loadSetup(); await loadOverview(); $("admin-key").value = ""; $("login").hidden = true; $("console").hidden = false; $("login-error").textContent = "";
    if (!setup.connections.some((item) => item.configured)) document.querySelector('[data-view="setup"]').click();
  } catch (error) { adminKey = ""; $("login-error").textContent = error.message; }
});

$("lock").addEventListener("click", () => { adminKey = ""; $("console").hidden = true; $("login").hidden = false; $("new-key").replaceChildren(); $("detail-body").replaceChildren(); $("detail").close(); document.querySelectorAll('input[type="password"]').forEach((node) => { node.value = ""; }); });
$("refresh").addEventListener("click", refresh);
$("close-detail").addEventListener("click", () => $("detail").close());

$("app-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  const payload = {app_id: form.get("app_id"), allowed_models: form.get("allowed_models").split(",").map((value) => value.trim()).filter(Boolean), capture_content: form.has("capture_content")};
  if (form.get("rate_limit_per_minute")) payload.rate_limit_per_minute = Number(form.get("rate_limit_per_minute"));
  try {
    const response = await api("/apps", {method: "POST", body: JSON.stringify(payload)}); const item = await response.json();
    $("new-key").hidden = false; $("new-key").textContent = `Copy now — shown once: ${item.api_key}`; notice("Application key created"); await loadApps();
  } catch (error) { notice(error.message); }
});

$("provider-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const element = event.currentTarget; const form = new FormData(element);
  try {
    await api("/provider-keys", {method: "PUT", body: JSON.stringify(Object.fromEntries(form))}); element.elements.key.value = ""; notice("Provider key stored"); await loadProviderKeys();
  } catch (error) { notice(error.message); }
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
    const response = await api("/logs/export"); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "gateway-events.json"; link.click(); URL.revokeObjectURL(url);
  } catch (error) { notice(error.message); }
});
