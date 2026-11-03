/** The one path to the admin API: session cookie, safe errors, and expiry handling. */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

interface CallOptions {
  method?: string;
  body?: unknown;
  etag?: string | null;
  signal?: AbortSignal;
}

/** Whether the gateway answered lately, so one banner can speak for every page during an outage. */
let reachable = true;
const listeners = new Set<() => void>();
const setReachable = (value: boolean) => {
  if (value === reachable) return;
  reachable = value;
  listeners.forEach((listener) => listener());
};
export const reachability = {
  get: () => reachable,
  subscribe: (listener: () => void) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

let sessionExpired: () => void = () => {};
export const onSessionExpired = (handler: () => void) => {
  sessionExpired = handler;
};

export async function call(path: string, options: CallOptions = {}): Promise<Response> {
  const headers: Record<string, string> = { "X-Gateway-Console": "1" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.etag) headers["If-Match"] = options.etag;
  let response: Response;
  try {
    response = await fetch(`/admin/api${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      cache: "no-store",
      credentials: "same-origin",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    setReachable(false);
    throw new ApiError("The gateway could not be reached", 0, "unreachable");
  }
  setReachable(response.status < 502);
  if (!response.ok) {
    let message = "The gateway could not complete that request";
    let code: string | undefined;
    try {
      const error = (await response.json()).error;
      message = error.message;
      code = error.code;
    } catch {
      /* Keep the generic message for a non-JSON failure. */
    }
    if (response.status === 401 && path !== "/session") sessionExpired();
    throw new ApiError(message, response.status, code);
  }
  return response;
}

export const getJson = async <T,>(path: string, signal?: AbortSignal): Promise<T> =>
  (await call(path, { signal })).json();

export const send = async <T = unknown,>(path: string, options: CallOptions): Promise<T> => {
  const response = await call(path, options);
  return (response.status === 204 ? null : response.json()) as T;
};

export interface Versioned<T> {
  data: T;
  etag: string | null;
}

export const getVersioned = async <T,>(path: string, signal?: AbortSignal): Promise<Versioned<T>> => {
  const response = await call(path, { signal });
  return { data: await response.json(), etag: response.headers.get("ETag") };
};

export const query = (values: Record<string, string | number | boolean | null | undefined>) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
};

export const message = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong";
