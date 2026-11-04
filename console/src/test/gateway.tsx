import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";

export interface Sent {
  method: string;
  path: string;
  query: URLSearchParams;
  body: any;
  headers: Record<string, string>;
  signal?: AbortSignal | null;
}

type Handler = (request: Sent) => Response | Promise<Response> | undefined;

export const respond = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  body === null
    ? new Response(null, { status, headers })
    : new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

export const failure = (status: number, message: string, code = "error") => respond({ error: { message, code, type: "error" } }, status);

export const APP = {
  app_id: "sample-app",
  project_id: "alpha",
  allowed_models: ["ollama:small"],
  key_prefix: "m87_fixture",
  active_key_count: 1,
  rate_limit_per_minute: null,
  max_concurrent_requests: null,
};

export const EVENT = {
  request_id: "fixture-request",
  created_at: "2026-11-03T12:00:00+00:00",
  project_id: "alpha",
  app_id: "sample-app",
  key_id: "abcdef1234567890",
  endpoint: "chat",
  model: "small",
  routed_model: "ollama:small",
  status_code: 200,
  http_status_code: 200,
  latency_ms: 12,
  prompt_tokens: 8,
  completion_tokens: 5,
  total_tokens: 13,
  error_type: null,
  cache_status: "disabled",
  request_outcome: "completed",
  capture_enabled: 0,
};

const CONNECTION = {
  provider: "ollama",
  label: "Ollama",
  requires_key: false,
  model_discovery: true,
  configured: true,
  has_stored_key: false,
  config: { enabled: true, base_url: "http://saved:11434", timeout_seconds: 300 },
  capability_matrix: { streaming: true, tools: true },
};

const defaults: Record<string, unknown> = {
  "GET /sign-in-options": { sso: false },
  "GET /about": { version: "9.8.7", revision: "abcdef1234567890" },
  "GET /overview": { requests: 1, total_tokens: 13, prompt_tokens: 8, completion_tokens: 5, cache_hits: 0, errors: 0, usage_unknown: 0, average_latency_ms: 12 },
  "GET /usage": {
    series: [{ bucket: "2026-11-03T12:00:00Z", requests: 1, total_tokens: 13 }],
    by_app: [{ app_id: "sample-app", requests: 1, prompt_tokens: 8, completion_tokens: 5, total_tokens: 13, errors: 0 }, { app_id: null, requests: 1, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, errors: 1 }],
    by_model: [{ model: "ollama:small", requests: 1, prompt_tokens: 8, completion_tokens: 5, total_tokens: 13, errors: 0 }],
    by_endpoint: [{ endpoint: "chat", requests: 1, prompt_tokens: 8, completion_tokens: 5, total_tokens: 13, errors: 0 }],
  },
  "GET /logs": { items: [EVENT], next_cursor: null },
  "GET /logs/fixture-request": { ...EVENT, request_content_status: "disabled", response_content_status: "disabled" },
  "GET /logging-health": { ok: true, capture_enabled: false, scope: "", items: [], traffic_retention_days: 30, content_retention_days: 7, usage_retention_days: 365, export: { enabled: false } },
  "GET /projects": { items: [{ project_id: "alpha", name: "Alpha", app_count: 1 }, { project_id: "default", name: "Default project", app_count: 0 }] },
  "GET /app-names": { items: ["retired-app", "sample-app"] },
  "GET /apps": { items: [APP] },
  "GET /apps/sample-app/keys": { items: [{ key_id: "key-one-abcdef", key_prefix: "m87_fixture", created_at: "2026-11-01T00:00:00+00:00", expires_at: null, revoked_at: null, last_used_at: null, active: true }] },
  "GET /setup": { default_model: "ollama:small", capture_content: false, connections: [CONNECTION] },
  "GET /diagnostics": { ready: true, default_model: "ollama:small", checks: [{ name: "Endpoint", ok: true, message: "" }], active_requests: 0 },
  "GET /connections/ollama/models": { items: ["ollama:small", "ollama:large"] },
  "GET /provider-keys": { items: [] },
  "GET /management-events": { items: [] },
  "GET /destinations": { items: [{ name: "Local SQLite", type: "events", target: "/data", enabled: true }] },
  "GET /storage": { ok: true, backend: "sqlite", verified: false, database_bytes: 1048576, wal_bytes: 0, free_disk_bytes: 1073741824, schema_version: 11, checks: [{ name: "Database", ok: true, message: "" }], warnings: [] },
};

export function gateway(handler: Handler = () => undefined, { signedIn = true } = {}) {
  const requests: Sent[] = [];
  const state = { signedIn };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://gateway.test");
    const method = init.method ?? "GET";
    const path = url.pathname.replace("/admin/api", "");
    const request: Sent = {
      method,
      path,
      query: url.searchParams,
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
      headers: (init.headers ?? {}) as Record<string, string>,
      signal: init.signal,
    };
    requests.push(request);
    const custom = await handler(request);
    if (custom) return custom;
    if (path === "/session") {
      if (method === "GET") return state.signedIn ? respond({ authenticated: true, actor: "admin-key", role: "admin", method: "key" }) : failure(401, "Missing or invalid admin key");
      if (method === "DELETE") {
        state.signedIn = false;
        return respond(null, 204);
      }
      if (request.body?.key === "correct-key") {
        state.signedIn = true;
        return respond(null, 204);
      }
      return failure(401, "Missing or invalid admin key");
    }
    const known = defaults[`${method} ${path}`];
    if (known !== undefined) return respond(known);
    return failure(404, `No fixture for ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    requests,
    find: (method: string, path: string) => requests.filter((item) => item.method === method && item.path === path),
    last: (method: string, path: string) => requests.filter((item) => item.method === method && item.path === path).at(-1),
  };
}

export function openConsole(route = "overview") {
  window.location.hash = `#/${route}`;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
  const user = userEvent.setup();
  const view = render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  return { user, ...view };
}

export const heading = (name: string) => screen.findByRole("heading", { name });
