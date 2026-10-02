let adminKey = "";
let activeView = "overview";
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
  table(target, ["Time", "App", "Model", "Status", "Tokens", "Latency"], rows.slice(0, limit), (row, item) => {
    row.dataset.id = item.request_id;
    cell(row, new Date(item.created_at).toLocaleString());
    cell(row, item.app_id);
    cell(row, item.routed_model || item.model);
    const status = cell(row, item.status_code);
    status.className = `status ${item.status_code >= 400 ? "error" : ""}`;
    cell(row, item.total_tokens);
    cell(row, item.latency_ms == null ? null : `${item.latency_ms} ms`);
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
  table($("apps"), ["Application", "Key prefix", "Models", "Content", ""], (await response.json()).items, (row, item) => {
    cell(row, item.app_id); cell(row, `${item.key_prefix}…`); cell(row, item.allowed_models.join(", ")); cell(row, item.capture_content ? "Enabled" : "Off");
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

const loaders = {overview: loadOverview, logs: loadLogs, apps: loadApps, keys: loadProviderKeys, destinations: loadDestinations};

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
    await loadOverview(); $("admin-key").value = ""; $("login").hidden = true; $("console").hidden = false; $("login-error").textContent = "";
  } catch (error) { adminKey = ""; $("login-error").textContent = error.message; }
});

$("lock").addEventListener("click", () => { adminKey = ""; $("console").hidden = true; $("login").hidden = false; });
$("refresh").addEventListener("click", refresh);
$("close-detail").addEventListener("click", () => $("detail").close());

$("app-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  const payload = {app_id: form.get("app_id"), allowed_models: form.get("allowed_models").split(",").map((value) => value.trim()).filter(Boolean), capture_content: form.has("capture_content")};
  try {
    const response = await api("/apps", {method: "POST", body: JSON.stringify(payload)}); const item = await response.json();
    $("new-key").hidden = false; $("new-key").textContent = `Copy now — shown once: ${item.api_key}`; notice("Application key created"); await loadApps();
  } catch (error) { notice(error.message); }
});

$("provider-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  try {
    await api("/provider-keys", {method: "PUT", body: JSON.stringify(Object.fromEntries(form))}); event.currentTarget.elements.key.value = ""; notice("Provider key stored"); await loadProviderKeys();
  } catch (error) { notice(error.message); }
});

$("export").addEventListener("click", async (event) => {
  event.preventDefault();
  try {
    const response = await api("/logs/export"); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "gateway-events.json"; link.click(); URL.revokeObjectURL(url);
  } catch (error) { notice(error.message); }
});
