const MAX_BODY_BYTES = 256 * 1024;
const CHAT_FIELDS = new Set([
  "model",
  "messages",
  "temperature",
  "max_tokens",
  "task",
  "stream",
]);

async function secretMatches(presented, expected) {
  if (!presented || !expected || expected.length < 32) return false;
  const encoder = new TextEncoder();
  const [left, right] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(presented)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const a = new Uint8Array(left);
  const b = new Uint8Array(right);
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) difference |= a[index] ^ b[index];
  return difference === 0;
}

function jsonError(status, code, message) {
  return Response.json({ error: { type: "worker_error", code, message } }, { status });
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return jsonError(405, "method_not_allowed", "Use POST for this test relay.");
    }

    const scheme = request.headers.get("Authorization")?.match(/^Bearer\s+(.+)$/i);
    if (!(await secretMatches(scheme?.[1]?.trim(), env.CLIENT_API_KEY))) {
      return jsonError(401, "invalid_client_key", "Unauthorized.");
    }
    if (!env.GATEWAY_URL || !env.GATEWAY_API_KEY) {
      return jsonError(503, "relay_not_configured", "The gateway relay is unavailable.");
    }
    let gatewayUrl;
    try {
      gatewayUrl = new URL(env.GATEWAY_URL);
    } catch {
      return jsonError(503, "relay_not_configured", "The gateway relay is unavailable.");
    }
    if (
      gatewayUrl.protocol !== "https:" ||
      gatewayUrl.username ||
      gatewayUrl.password ||
      Boolean(env.GATEWAY_ACCESS_CLIENT_ID) !== Boolean(env.GATEWAY_ACCESS_CLIENT_SECRET)
    ) {
      return jsonError(503, "relay_not_configured", "The gateway relay is unavailable.");
    }

    const declaredLength = Number(request.headers.get("Content-Length") ?? 0);
    if (declaredLength > MAX_BODY_BYTES) {
      return jsonError(413, "request_too_large", "Request body is too large.");
    }
    const rawBody = await request.arrayBuffer();
    if (rawBody.byteLength > MAX_BODY_BYTES) {
      return jsonError(413, "request_too_large", "Request body is too large.");
    }

    let payload;
    try {
      payload = JSON.parse(new TextDecoder().decode(rawBody));
    } catch {
      return jsonError(400, "invalid_json", "Request body must be valid JSON.");
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return jsonError(400, "invalid_request", "Request body must be a JSON object.");
    }
    if (Object.keys(payload).some((field) => !CHAT_FIELDS.has(field)) || payload.stream === true) {
      return jsonError(422, "unsupported_request", "This relay supports non-streaming text chat.");
    }

    const headers = new Headers({
      Authorization: `Bearer ${env.GATEWAY_API_KEY}`,
      "Content-Type": "application/json",
    });
    if (env.GATEWAY_ACCESS_CLIENT_ID && env.GATEWAY_ACCESS_CLIENT_SECRET) {
      headers.set("CF-Access-Client-Id", env.GATEWAY_ACCESS_CLIENT_ID);
      headers.set("CF-Access-Client-Secret", env.GATEWAY_ACCESS_CLIENT_SECRET);
    }

    let upstream;
    try {
      upstream = await fetch(new URL("/v1/chat/completions", gatewayUrl), {
        method: "POST",
        headers,
        body: JSON.stringify({ ...payload, stream: false }),
      });
    } catch {
      return jsonError(503, "gateway_unreachable", "The model gateway is unavailable.");
    }

    const responseHeaders = new Headers();
    for (const name of ["Content-Type", "X-Request-ID"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  },
};
