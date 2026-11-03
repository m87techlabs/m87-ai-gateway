import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { APP, EVENT, failure, gateway, heading, openConsole, respond } from "./gateway";

beforeEach(() => {
  window.location.hash = "";
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const dialog = () => screen.findByRole("dialog");

describe("session", () => {
  it("signs in, clears the key field and does not send it again", async () => {
    const mock = gateway(undefined, { signedIn: false });
    const { user } = openConsole();
    await user.type(await screen.findByLabelText("Admin key"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Missing or invalid admin key")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Admin key"));
    await user.type(screen.getByLabelText("Admin key"), "correct-key");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await heading("Overview");
    expect(mock.requests.filter((item) => item.body?.key)).toHaveLength(2);
    expect(mock.requests.filter((item) => item.method === "GET").every((item) => !item.headers.Authorization)).toBe(true);
  });

  it("skips sign-in when the session is still valid, as after a refresh", async () => {
    gateway();
    openConsole();
    await heading("Overview");
    expect(screen.queryByLabelText("Admin key")).not.toBeInTheDocument();
  });

  it("returns to sign-in when the session expires, instead of showing broken pages", async () => {
    let expired = false;
    const mock = gateway((request) => (expired && request.path !== "/session" ? failure(401, "Missing or invalid admin key") : undefined));
    const { user } = openConsole();
    await heading("Overview");
    expired = true;
    await user.click(screen.getByRole("link", { name: "Logs" }));
    expect(await screen.findByLabelText("Admin key")).toBeInTheDocument();
    expect(mock.requests.length).toBeGreaterThan(0);
  });

  it("locking ends the session and removes what was on screen", async () => {
    const mock = gateway();
    const { user } = openConsole("logs");
    expect(await screen.findByText("sample-app", { selector: "td" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Lock console" }));
    expect(await screen.findByLabelText("Admin key")).toBeInTheDocument();
    expect(mock.last("DELETE", "/session")).toBeTruthy();
    expect(screen.queryByText("sample-app")).not.toBeInTheDocument();
  });
});

describe("outage", () => {
  it("shows one banner, keeps the last data, and recovers by itself", async () => {
    let down = false;
    const mock = gateway(() => {
      if (down) throw new TypeError("Failed to fetch");
      return undefined;
    });
    const { user } = openConsole("logs");
    expect(await screen.findByText("ollama:small")).toBeInTheDocument();
    down = true;
    await user.click(screen.getByRole("link", { name: "Overview" }));
    expect(await screen.findByText("The gateway can't be reached")).toBeInTheDocument();
    expect(screen.queryByText("This could not be loaded")).not.toBeInTheDocument();
    expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument();
    down = false;
    const before = mock.requests.length;
    await waitFor(() => expect(screen.queryByText("The gateway can't be reached")).not.toBeInTheDocument(), { timeout: 5000 });
    await waitFor(() => expect(mock.requests.length).toBeGreaterThan(before + 1));
  });
});

describe("filters", () => {
  it("scopes the dashboard by project and application, and labels failed logins", async () => {
    const mock = gateway();
    const { user } = openConsole();
    expect(await screen.findByText("Unauthenticated")).toBeInTheDocument();
    await user.selectOptions(await screen.findByLabelText("Project"), "alpha");
    await waitFor(() => expect(mock.last("GET", "/usage")?.query.get("project_id")).toBe("alpha"));
    await screen.findByRole("option", { name: "sample-app" });
    await user.selectOptions(screen.getByLabelText("Application"), "sample-app");
    await waitFor(() => {
      expect(mock.last("GET", "/overview")?.query.get("app_id")).toBe("sample-app");
      expect(mock.last("GET", "/usage")?.query.get("app_id")).toBe("sample-app");
      expect(mock.last("GET", "/usage")?.query.get("project_id")).toBe("alpha");
    });
  });

  it("keeps filters while moving between pages", async () => {
    const mock = gateway();
    const { user } = openConsole();
    await screen.findByRole("option", { name: "sample-app" });
    await user.selectOptions(await screen.findByLabelText("Application"), "sample-app");
    await user.click(screen.getByRole("link", { name: "Logs" }));
    await waitFor(() => expect(mock.requests.some((item) => item.path === "/logs" && item.query.get("limit") === "50" && item.query.get("app_id") === "sample-app")).toBe(true));
    expect(screen.getByLabelText("Application")).toHaveValue("sample-app");
  });

  it("does not apply the application filter to the audit log", async () => {
    const mock = gateway();
    const { user } = openConsole();
    await screen.findByRole("option", { name: "sample-app" });
    await user.selectOptions(await screen.findByLabelText("Application"), "sample-app");
    await user.click(screen.getByRole("link", { name: "Audit log" }));
    await waitFor(() => expect(mock.last("GET", "/management-events")).toBeTruthy());
    expect(mock.last("GET", "/management-events")?.query.get("app_id")).toBeNull();
  });
});

describe("logs", () => {
  it("searches and pages without losing filters, and exports what was asked for", async () => {
    const mock = gateway((request) => {
      if (request.path === "/logs" && !request.query.get("cursor") && request.method === "GET") return respond({ items: [EVENT], next_cursor: "next-page" });
      if (request.path === "/logs" && request.query.get("cursor") === "next-page") return respond({ items: [{ ...EVENT, request_id: "older", model: "older-model", routed_model: "ollama:older-model" }], next_cursor: null });
      if (request.path === "/logs/export") return new Response("[]");
      return undefined;
    });
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const { user } = openConsole("logs");
    await screen.findByText("ollama:small");
    await user.selectOptions(await screen.findByLabelText("Project"), "alpha");
    await user.click(await screen.findByRole("button", { name: "Older" }));
    expect(await screen.findByText("ollama:older-model")).toBeInTheDocument();
    expect(mock.requests.find((item) => item.query.get("cursor") === "next-page")?.query.get("project_id")).toBe("alpha");
    await user.click(screen.getByRole("button", { name: "Newer" }));
    await screen.findByText("ollama:small");
    await user.type(screen.getByLabelText("Request ID"), "fixture-request");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(mock.last("GET", "/logs")?.query.get("request_id")).toBe("fixture-request"));
    await user.click(screen.getByRole("button", { name: "Export JSON" }));
    await waitFor(() => expect(mock.last("GET", "/logs/export")?.query.get("include_content")).toBe("false"));
    await user.click(screen.getByLabelText("Include captured input and output"));
    await user.click(screen.getByRole("button", { name: "Export JSON" }));
    await waitFor(() => expect(mock.last("GET", "/logs/export")?.query.get("include_content")).toBe("true"));
    expect(mock.last("GET", "/logs/export")?.query.get("project_id")).toBe("alpha");
  });

  it("names exactly what a delete will remove, and needs confirmation", async () => {
    const mock = gateway((request) => (request.method === "DELETE" && request.path === "/logs" ? respond({ deleted: 3 }) : undefined));
    const { user } = openConsole("logs");
    await screen.findByRole("option", { name: "sample-app" });
    await user.selectOptions(await screen.findByLabelText("Application"), "sample-app");
    await user.click(screen.getByRole("button", { name: "Delete all logs" }));
    let box = within(await dialog());
    await user.click(box.getByRole("button", { name: "Cancel" }));
    expect(mock.last("DELETE", "/logs")).toBeUndefined();
    await user.selectOptions(screen.getByLabelText("Project"), "alpha");
    await user.click(await screen.findByRole("button", { name: "Delete selected project logs" }));
    box = within(await dialog());
    expect(box.getByRole("heading", { name: "Delete logs for project alpha?" })).toBeInTheDocument();
    await user.click(box.getByRole("button", { name: "Delete logs" }));
    await waitFor(() => expect(mock.last("DELETE", "/logs")?.body).toEqual({ confirmation: "DELETE", project_id: "alpha" }));
    expect(await screen.findByText("3 records deleted")).toBeInTheDocument();
  });

  it.each([
    ["disabled", "Capture was off"],
    ["expired", "expired under its retention"],
    ["deleted", "deleted by an operator"],
    ["unknown", "older record"],
  ])("explains %s content without inventing any", async (status, expected) => {
    gateway((request) =>
      request.path === "/logs/fixture-request" ? respond({ ...EVENT, request_content: null, response_content: null, request_content_status: status, response_content_status: status }) : undefined,
    );
    const { user } = openConsole("logs");
    await user.click(await screen.findByText("ollama:small"));
    const box = within(await dialog());
    expect((await box.findAllByText(new RegExp(expected))).length).toBe(2);
  });

  it("distinguishes a cancelled stream with partial output", async () => {
    gateway((request) => {
      const event = { ...EVENT, streaming: 1, status_code: 499, http_status_code: 200, request_outcome: "cancelled", response_content_partial: 1, request_content: [{ role: "user", content: "question" }], request_content_status: "captured", response_content: [{ index: 0, message: { role: "assistant", content: "partial words" } }], response_content_status: "partial" };
      if (request.path === "/logs/fixture-request") return respond(event);
      if (request.path === "/logs") return respond({ items: [event], next_cursor: null });
      return undefined;
    });
    const { user } = openConsole("logs");
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    await user.click(screen.getByText("ollama:small"));
    const box = within(await dialog());
    expect(await box.findByText("Partial")).toBeInTheDocument();
    expect(box.getAllByText(/partial words/, { selector: "pre" }).length).toBeGreaterThan(0);
    expect(box.getByText("HTTP status sent").nextSibling).toHaveTextContent("200");
    expect(box.getByText("Status").nextSibling).toHaveTextContent("499");
  });

  it("opens a request from a link", async () => {
    gateway();
    openConsole("logs?request_id=fixture-request");
    expect(await screen.findByRole("heading", { name: "Request details" })).toBeInTheDocument();
    expect(screen.getByLabelText("Request ID")).toHaveValue("fixture-request");
  });

  it("makes recording and export problems impossible to miss", async () => {
    gateway((request) =>
      request.path === "/logging-health"
        ? respond({ ok: false, capture_enabled: true, scope: "", items: [{ destination: "control_store", last_write_ok: false, successful_writes: 1, failed_writes: 2 }], traffic_retention_days: 30, content_retention_days: 7, usage_retention_days: 365, export: { enabled: true, delivery_state: "retrying", pending: 4, failed_attempts: 5, dropped: 1 } })
        : undefined,
    );
    openConsole("logs");
    expect(await screen.findByText("Recording needs attention")).toBeInTheDocument();
    expect(screen.getByText("Log export is retrying")).toBeInTheDocument();
    expect(screen.getByText(/control_store: 2 failed writes/)).toBeInTheDocument();
    expect(screen.getByText("Capture on")).toBeInTheDocument();
  });

  it("shows a failure and offers a retry, instead of a blank page", async () => {
    let healthy = false;
    gateway((request) => (request.path === "/logs" && !healthy ? failure(503, "Storage is busy") : undefined));
    const { user } = openConsole("logs");
    expect(await screen.findByText("Storage is busy")).toBeInTheDocument();
    healthy = true;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("ollama:small")).toBeInTheDocument();
  });

  it("renders untrusted text as text", async () => {
    const hostile = '<img src=x onerror="window.hacked=1">';
    gateway((request) => (request.path === "/logs" ? respond({ items: [{ ...EVENT, app_id: hostile, routed_model: hostile }], next_cursor: null }) : undefined));
    openConsole("logs");
    expect(await screen.findAllByText(hostile)).toHaveLength(2);
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("applications", () => {
  it("creates an app with discovered models and shows its key once, with setup snippets", async () => {
    const mock = gateway((request) => (request.method === "POST" && request.path === "/apps" ? respond({ ...APP, ...request.body, api_key: "m87_shown_once" }, 201) : undefined));
    const { user } = openConsole("applications");
    await user.click(await screen.findByRole("button", { name: "Create application" }));
    const box = within(await dialog());
    await user.type(box.getByLabelText("Name"), "new-app");
    await user.selectOptions(box.getByLabelText("Project"), await box.findByRole("option", { name: "Alpha" }));
    await user.click(await box.findByLabelText("ollama:large"));
    await user.type(box.getByLabelText("Requests per minute"), "60");
    await user.click(box.getByRole("button", { name: "Create application" }));
    expect(await screen.findByText("m87_shown_once")).toBeInTheDocument();
    expect(mock.last("POST", "/apps")?.body).toEqual({ app_id: "new-app", project_id: "alpha", allowed_models: ["auto", "ollama:small", "ollama:large"], rate_limit_per_minute: 60 });
    expect(screen.getByText(/base_url=/)).toHaveTextContent("m87_shown_once");
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByText("m87_shown_once")).not.toBeInTheDocument());
  });

  it("shows an app's own activity", async () => {
    const mock = gateway();
    openConsole("applications/sample-app");
    await heading("sample-app");
    await waitFor(() => {
      expect(mock.last("GET", "/overview")?.query.get("app_id")).toBe("sample-app");
      expect(mock.last("GET", "/usage")?.query.get("hours")).toBe("24");
    });
    expect((await screen.findAllByText("Chat")).length).toBeGreaterThan(0);
    expect(screen.getByRole("tab", { name: "Keys" })).toBeInTheDocument();
  });

  it("keeps history for an app that no longer has settings", async () => {
    gateway();
    openConsole("applications/retired-app");
    expect(await screen.findByText(/deleted or comes from a YAML file/)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Keys" })).not.toBeInTheDocument();
  });

  it("saves models, limits and project without touching keys", async () => {
    const mock = gateway((request) => (request.method === "PATCH" ? respond(null, 204) : undefined));
    const { user } = openConsole("applications/sample-app");
    await user.click(await screen.findByRole("tab", { name: "Settings" }));
    await user.click(await screen.findByLabelText("ollama:large"));
    await user.click(screen.getByRole("button", { name: "Save models" }));
    await waitFor(() => expect(mock.last("PATCH", "/apps/sample-app/models")?.body).toEqual({ allowed_models: ["ollama:small", "ollama:large"] }));
    await user.type(screen.getByLabelText("Requests per minute"), "30");
    await user.click(screen.getByRole("button", { name: "Save limits" }));
    await waitFor(() => expect(mock.last("PATCH", "/apps/sample-app/limits")?.body).toEqual({ rate_limit_per_minute: 30, max_concurrent_requests: null }));
    await user.selectOptions(screen.getByLabelText("Project"), "default");
    await waitFor(() => expect(mock.last("PATCH", "/apps/sample-app/project")?.body).toEqual({ project_id: "default" }));
    expect(mock.requests.some((item) => item.path.endsWith("/keys") && item.method !== "GET")).toBe(false);
  });

  it("rotates keys with overlap and confirms each revocation", async () => {
    const mock = gateway((request) => {
      if (request.method === "POST" && request.path === "/apps/sample-app/keys") return respond({ api_key: "m87_replacement", key_id: "two" }, 201);
      if (request.method === "DELETE") return respond(null, 204);
      return undefined;
    });
    const { user } = openConsole("applications/sample-app");
    await user.click(await screen.findByRole("tab", { name: "Keys" }));
    expect(await screen.findByText("No use recorded")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Expires after (days)"), "30");
    await user.click(screen.getByRole("button", { name: "Create key" }));
    expect(await screen.findByText("m87_replacement")).toBeInTheDocument();
    expect(mock.last("POST", "/apps/sample-app/keys")?.body).toEqual({ revoke_existing: false, expires_in_days: 30 });
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    const box = within(await dialog());
    await user.click(box.getByRole("button", { name: "Cancel" }));
    expect(mock.requests.some((item) => item.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Revoke key" }));
    await waitFor(() => expect(mock.last("DELETE", "/apps/sample-app/keys/key-one-abcdef")).toBeTruthy());
  });

  it("does not reveal a key that arrives after the console was locked", async () => {
    let finish: (response: Response) => void = () => undefined;
    gateway((request) => (request.method === "POST" && request.path === "/apps/sample-app/keys" ? new Promise<Response>((resolve) => (finish = resolve)) : undefined));
    const { user } = openConsole("applications/sample-app");
    await user.click(await screen.findByRole("tab", { name: "Keys" }));
    await user.click(await screen.findByRole("button", { name: "Create key" }));
    await user.click(screen.getByRole("button", { name: "Lock console" }));
    await screen.findByLabelText("Admin key");
    finish(respond({ api_key: "m87_too_late" }, 201));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText("m87_too_late")).not.toBeInTheDocument();
  });
});

describe("providers", () => {
  it("tests unsaved fields without saving, and drops a result once the form changes", async () => {
    let finish: (response: Response) => void = () => undefined;
    const mock = gateway((request) => (request.path === "/connections/ollama/test" ? new Promise<Response>((resolve) => (finish = resolve)) : undefined));
    const { user } = openConsole("providers");
    await user.click(await screen.findByRole("button", { name: "Configure Ollama" }));
    const box = within(await dialog());
    const endpoint = box.getByLabelText("Endpoint URL");
    await user.clear(endpoint);
    await user.type(endpoint, "http://draft:11434");
    await user.click(box.getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(mock.last("POST", "/connections/ollama/test")?.body.config.base_url).toBe("http://draft:11434"));
    await user.type(endpoint, "0");
    finish(respond({ ok: true, message: "stale answer", latency_ms: 4 }));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(box.queryByText(/stale answer/)).not.toBeInTheDocument();
    expect(mock.last("PUT", "/connections/ollama")).toBeUndefined();
    expect(endpoint).toHaveValue("http://draft:114340");
  });

  it("saves with the version it loaded, so a stale edit is refused", async () => {
    const mock = gateway((request) => {
      if (request.method === "GET" && request.path === "/setup") return respond({ default_model: "ollama:small", capture_content: true, connections: [{ provider: "ollama", label: "Ollama", requires_key: false, model_discovery: true, configured: true, has_stored_key: false, config: { enabled: true, base_url: "http://saved:11434", timeout_seconds: 300 }, capability_matrix: {} }] }, 200, { ETag: '"7"' });
      if (request.method === "PUT" && request.path === "/connections/ollama") return failure(409, "Configuration changed; refresh history");
      if (request.method === "PUT" && request.path === "/setup") return respond(null, 204);
      return undefined;
    });
    const { user } = openConsole("providers");
    const model = await screen.findByLabelText("Default model");
    await user.clear(model);
    await user.type(model, "ollama:large");
    await user.click(within(model.closest("form")!).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mock.last("PUT", "/setup")?.body).toEqual({ default_model: "ollama:large", capture_content: true }));
    expect(mock.last("PUT", "/setup")?.headers["If-Match"]).toBe('"7"');
    await user.click(screen.getByRole("button", { name: "Configure Ollama" }));
    const box = within(await dialog());
    await user.type(box.getByLabelText("API key (optional)"), "provider-secret");
    await user.click(box.getByRole("button", { name: "Save" }));
    expect(await box.findByText("Configuration changed; refresh history")).toBeInTheDocument();
    expect(mock.last("PUT", "/connections/ollama")?.headers["If-Match"]).toBe('"7"');
    expect(mock.last("PUT", "/connections/ollama")?.body.key).toBe("provider-secret");
  });
});

describe("first-time provider setup", () => {
  it("enables a connection when it is first configured", async () => {
    const fresh = { provider: "ollama", label: "Ollama", requires_key: false, model_discovery: true, configured: false, has_stored_key: false, config: { enabled: false, base_url: "http://localhost:11434", timeout_seconds: 300 }, capability_matrix: {} };
    const mock = gateway((request) => {
      if (request.method === "GET" && request.path === "/setup") return respond({ default_model: "ollama:llama3", capture_content: false, connections: [fresh] });
      if (request.method === "PUT") return respond(null, 204);
      return undefined;
    });
    const { user } = openConsole("providers");
    await user.click(await screen.findByRole("button", { name: "Configure Ollama" }));
    const box = within(await dialog());
    expect(box.getByLabelText("Enable this connection")).toBeChecked();
    await user.click(box.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mock.last("PUT", "/connections/ollama")?.body.config.enabled).toBe(true));
  });
});

const FEATURES = [
  { id: "response_cache", name: "Response cache", group: "Traffic", summary: "Stores answers.", note: null, status: "off", enabled: false, toggleable: true, values: { ttl_seconds: 300 }, fields: [{ name: "ttl_seconds", label: "Keep answers for", kind: "number", minimum: 1, maximum: 86400, step: null, unit: "s", help: null }] },
  { id: "concurrency", name: "Concurrency limit", group: "Traffic", summary: "Limit.", note: null, status: "on", enabled: true, toggleable: false, values: { max_concurrent_requests: 64 }, fields: [{ name: "max_concurrent_requests", label: "Concurrent requests", kind: "number", minimum: 1, maximum: 10000, step: null, unit: null, help: null }] },
  { id: "blocklist", name: "Blocklist", group: "Safety", summary: "Rejects phrases.", note: null, status: "on", enabled: true, toggleable: true, values: { blocked_terms: ["one"] }, fields: [{ name: "blocked_terms", label: "Blocked phrases", kind: "terms", minimum: null, maximum: null, step: null, unit: null, help: null }] },
  { id: "task_routing", name: "Task routing", group: "Routing", summary: "Routes.", note: null, status: "on", enabled: true, toggleable: false, values: { routes: [] }, fields: [{ name: "routes", label: "Routes", kind: "routes", minimum: null, maximum: null, step: null, unit: null, help: null }] },
  { id: "budgets", name: "Budgets", group: "Safety", summary: "Limit spend.", note: null, status: "planned", enabled: false, toggleable: false, values: {}, fields: [] },
];

describe("features", () => {
  const withFeatures = (put: (request: { body: any }) => Response | undefined = () => undefined) =>
    gateway((request) => {
      if (request.method === "GET" && request.path === "/features") return respond({ items: FEATURES }, 200, { ETag: '"3"' });
      if (request.method === "PUT" && request.path.startsWith("/features/")) return put(request) ?? respond(FEATURES[0]);
      return undefined;
    });

  it("turns a feature on with the version it loaded", async () => {
    const mock = withFeatures();
    const { user } = openConsole("features");
    await user.click(await screen.findByRole("switch", { name: "Response cache" }));
    await waitFor(() => expect(mock.last("PUT", "/features/response_cache")?.body).toEqual({ enabled: true }));
    expect(mock.last("PUT", "/features/response_cache")?.headers["If-Match"]).toBe('"3"');
    expect(await screen.findByText("Response cache turned on")).toBeInTheDocument();
  });

  it("shows settings only for features that are on, and marks fixed and planned ones", async () => {
    withFeatures();
    openConsole("features");
    expect(await screen.findByLabelText("Concurrent requests")).toHaveValue(64);
    expect(screen.queryByLabelText("Keep answers for (s)")).not.toBeInTheDocument();
    expect(screen.getAllByText("Always on")).toHaveLength(2);
    expect(screen.getByText("Planned")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Budgets" })).not.toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Concurrency limit" })).not.toBeInTheDocument();
  });

  it("saves edited settings, and offers Save only once something changed", async () => {
    const mock = withFeatures();
    const { user } = openConsole("features");
    const phrases = await screen.findByLabelText("Blocked phrases");
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    await user.type(phrases, "\n two \n\n");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mock.last("PUT", "/features/blocklist")?.body).toEqual({ values: { blocked_terms: ["one", "two"] } }));
  });

  it("edits task routes", async () => {
    const mock = withFeatures();
    const { user } = openConsole("features");
    await user.click(await screen.findByRole("button", { name: "Add route" }));
    await user.type(screen.getByLabelText("Task 1"), "code");
    await user.type(screen.getByLabelText("Model 1"), "ollama:large");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mock.last("PUT", "/features/task_routing")?.body).toEqual({ values: { routes: [{ task: "code", model: "ollama:large" }] } }));
  });

  it("explains a refused save and reloads the latest values", async () => {
    const mock = withFeatures(() => failure(409, "Configuration changed; refresh history"));
    const { user } = openConsole("features");
    await user.click(await screen.findByRole("switch", { name: "Response cache" }));
    expect(await screen.findByText(/Settings changed elsewhere/)).toBeInTheDocument();
    await waitFor(() => expect(mock.find("GET", "/features").length).toBeGreaterThan(1));
  });

  it("keeps a validation failure on screen until dismissed", async () => {
    withFeatures(() => failure(422, "Check Concurrent requests"));
    const { user } = openConsole("features");
    const input = await screen.findByLabelText("Concurrent requests");
    await user.clear(input);
    await user.type(input, "65");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Check Concurrent requests")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Check Concurrent requests")).not.toBeInTheDocument();
  });
});

describe("configuration history", () => {
  const revisions = (restore: () => Response) =>
    gateway((request) => {
      if (request.path === "/configuration/revisions") return respond({ current_revision: 2, items: [{ revision_id: 2, created_at: "2026-11-03T00:00:00+00:00", action: "feature.metrics.updated", restored_from: null }, { revision_id: 1, created_at: "2026-11-02T00:00:00+00:00", action: "<b>setup</b>", restored_from: null }] });
      if (request.path === "/configuration/revisions/1") return respond({ scope: "Console settings only", settings: { default_model: "<i>ollama:old</i>" }, changed_provider_bindings: ["ollama"], changed_export_binding: false });
      if (request.path === "/configuration/revisions/1/restore") return restore();
      return undefined;
    });

  it("restores only after RESTORE is typed, and warns about credentials", async () => {
    const mock = revisions(() => respond({ revision_id: 3 }));
    const { user } = openConsole("history");
    expect(await screen.findByText("<b>setup</b>")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "Review and restore" });
    expect(buttons[0]).toBeDisabled();
    await user.click(buttons[1]);
    const box = within(await dialog());
    expect(await box.findByText(/<i>ollama:old<\/i>/)).toBeInTheDocument();
    expect(box.getByText("Credentials will be removed")).toBeInTheDocument();
    const restore = box.getByRole("button", { name: "Restore settings" });
    expect(restore).toBeDisabled();
    await user.type(box.getByLabelText("Type RESTORE to activate these settings"), "RESTORE");
    await user.click(box.getByLabelText("Remove credentials for the changed connections"));
    await user.click(restore);
    await waitFor(() => expect(mock.last("POST", "/configuration/revisions/1/restore")?.body).toEqual({ expected_revision: 2, confirmation: "RESTORE", clear_changed_credentials: true }));
  });

  it("stays open with the reason when a restore is stale", async () => {
    revisions(() => failure(409, "Configuration changed; refresh history"));
    const { user } = openConsole("history");
    await user.click((await screen.findAllByRole("button", { name: "Review and restore" }))[1]);
    const box = within(await dialog());
    await user.type(await box.findByLabelText("Type RESTORE to activate these settings"), "RESTORE");
    await user.click(box.getByRole("button", { name: "Restore settings" }));
    expect(await box.findByText("Configuration changed; refresh history")).toBeInTheDocument();
  });
});

describe("storage", () => {
  it("verifies only when asked and reports failures safely", async () => {
    const mock = gateway((request) =>
      request.path === "/storage/check" ? respond({ ok: false, backend: "sqlite", verified: true, database_bytes: 1, wal_bytes: 0, free_disk_bytes: 1, schema_version: 11, checks: [{ name: "Write probe", ok: false, message: "Check disk space and permissions." }], warnings: [] }) : undefined,
    );
    const { user } = openConsole("storage");
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    expect(mock.last("POST", "/storage/check")).toBeUndefined();
    await user.click(screen.getByRole("button", { name: "Verify integrity and write access" }));
    expect(await screen.findByText("Check disk space and permissions.")).toBeInTheDocument();
  });
});

describe("log export", () => {
  const SETTINGS = {
    adapters: ["loki", "webhook"],
    config: { enabled: false, adapter: "webhook", endpoint: null, use_stored_key: false, api_key_env: null, max_pending: 5000, retention_hours: 168, timeout_seconds: 5, poll_seconds: 1, retry_seconds: 2, max_retry_seconds: 300 },
    has_stored_key: false,
    has_any_stored_key: false,
    health: { enabled: false, delivery_state: "disabled", pending: 0, delivered: 0 },
    scope: "",
  };
  const exporting = (handler: (request: any) => Response | Promise<Response> | undefined = () => undefined) =>
    gateway((request) => {
      if (request.method === "GET" && request.path === "/log-export") return respond(SETTINGS, 200, { ETag: '"9"' });
      return handler(request);
    });

  it("saves a one-time token with the version it loaded, then forgets it", async () => {
    const mock = exporting((request) => (request.method === "PUT" && request.path === "/log-export" ? respond(null, 204) : undefined));
    const { user } = openConsole("export");
    await user.click(await screen.findByLabelText("Export request metadata"));
    await user.type(screen.getByLabelText("Receiver URL"), "https://collector.example.com/events");
    await user.selectOptions(screen.getByLabelText("Authentication"), "stored");
    await user.type(screen.getByLabelText("New bearer token"), "one-time-token");
    await user.click(screen.getByRole("button", { name: "Save and apply" }));
    await waitFor(() => expect(mock.last("PUT", "/log-export")).toBeTruthy());
    const sent = mock.last("PUT", "/log-export")!;
    expect(sent.headers["If-Match"]).toBe('"9"');
    expect(sent.body.key).toBe("one-time-token");
    expect(sent.body.config).toMatchObject({ enabled: true, use_stored_key: true, endpoint: "https://collector.example.com/events", max_pending: 5000 });
    await waitFor(() => expect(screen.getByLabelText("New bearer token")).toHaveValue(""));
  });

  it("tests a draft without saving", async () => {
    const mock = exporting((request) => (request.path === "/log-export/test" ? respond({ ok: true, message: "Receiver accepted the synthetic event." }) : undefined));
    const { user } = openConsole("export");
    await user.type(await screen.findByLabelText("Receiver URL"), "https://draft.example.com");
    await user.click(screen.getByRole("button", { name: "Send test event" }));
    expect(await screen.findByText("Receiver accepted the synthetic event.")).toBeInTheDocument();
    expect(mock.last("PUT", "/log-export")).toBeUndefined();
    expect(screen.getByLabelText("Receiver URL")).toHaveValue("https://draft.example.com");
  });

  it("clears the token when a save is stale, and says what to do", async () => {
    exporting((request) => (request.method === "PUT" ? failure(409, "Configuration changed.") : undefined));
    const { user } = openConsole("export");
    await user.selectOptions(await screen.findByLabelText("Authentication"), "stored");
    await user.type(screen.getByLabelText("New bearer token"), "secret-token");
    await user.click(screen.getByRole("button", { name: "Save and apply" }));
    expect(await screen.findByText(/re-enter a new token/)).toBeInTheDocument();
    expect(screen.getByLabelText("New bearer token")).toHaveValue("");
  });

  it("aborts a running test when the draft changes, or when the page goes away", async () => {
    const mock = exporting((request) => (request.path === "/log-export/test" ? new Promise<Response>(() => undefined) : undefined));
    const { user, unmount } = openConsole("export");
    await user.type(await screen.findByLabelText("Receiver URL"), "https://a.example.com");
    await user.click(screen.getByRole("button", { name: "Send test event" }));
    await waitFor(() => expect(mock.last("POST", "/log-export/test")).toBeTruthy());
    const first = mock.last("POST", "/log-export/test")!.signal!;
    expect(first.aborted).toBe(false);
    await user.type(screen.getByLabelText("Receiver URL"), "x");
    expect(first.aborted).toBe(true);
    expect(screen.getByText(/Draft changed/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send test event" }));
    await waitFor(() => expect(mock.find("POST", "/log-export/test")).toHaveLength(2));
    const second = mock.last("POST", "/log-export/test")!.signal!;
    unmount();
    expect(second.aborted).toBe(true);
  });

  it("offers Loki with the shared credential controls", async () => {
    exporting();
    const { user } = openConsole("export");
    await user.selectOptions(await screen.findByLabelText("Format"), "loki");
    expect(screen.getByText(/loki\/api\/v1\/push/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Authentication"), "environment");
    expect(screen.getByLabelText("Token environment variable")).toBeInTheDocument();
  });
});

describe("playground", () => {
  const stream = () =>
    new Response(
      new ReadableStream({
        start(controller) {
          const encoder = new TextEncoder();
          controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'));
          controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"lo"}}]}\n\ndata: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\ndata: [DONE]\n\n'));
          controller.close();
        },
      }),
      { status: 200, headers: { "X-Request-ID": "fixture-request" } },
    );

  it("uses the app key, streams the answer and links to its log", async () => {
    const mock = gateway((request) => (request.path === "/v1/chat/completions" ? stream() : undefined));
    const { user } = openConsole("playground");
    await user.type(await screen.findByLabelText("Application key"), "m87_app_key");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Hello")).toBeInTheDocument();
    const sent = mock.last("POST", "/v1/chat/completions")!;
    expect(sent.headers.Authorization).toBe("Bearer m87_app_key");
    expect(sent.body).toMatchObject({ model: "auto", stream: true, max_tokens: 256 });
    expect(await screen.findByText(/3 in · 2 out/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Logs" })).toHaveAttribute("href", "#/logs?request_id=fixture-request");
  });

  it("shows gateway errors from a complete response", async () => {
    gateway((request) => (request.path === "/v1/chat/completions" ? respond({ error: { message: "Model is not allowed for app" } }, 403) : undefined));
    const { user } = openConsole("playground");
    await user.type(await screen.findByLabelText("Application key"), "m87_app_key");
    await user.click(screen.getByLabelText("Stream the response"));
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Model is not allowed for app")).toBeInTheDocument();
    expect(screen.getByText(/HTTP 403/)).toBeInTheDocument();
  });

  it("stops a running request, and stops it on lock too", async () => {
    const mock = gateway((request) =>
      request.path === "/v1/chat/completions"
        ? new Promise<Response>((_, reject) => request.signal?.addEventListener("abort", () => reject(Object.assign(new Error("stopped"), { name: "AbortError" }))))
        : undefined,
    );
    const { user } = openConsole("playground");
    await user.type(await screen.findByLabelText("Application key"), "m87_app_key");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByText(/Stopped/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("button", { name: "Stop" });
    const signal = mock.last("POST", "/v1/chat/completions")!.signal!;
    await user.click(screen.getByRole("button", { name: "Lock console" }));
    await screen.findByLabelText("Admin key");
    expect(signal.aborted).toBe(true);
    expect(screen.queryByDisplayValue("m87_app_key")).not.toBeInTheDocument();
  });
});
