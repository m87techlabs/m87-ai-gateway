# Connect your app

An app that already speaks the OpenAI API needs two changes: its base URL and its API
key. Provider credentials stay in the gateway.

## Base URL and key

| Your app runs | Base URL |
| --- | --- |
| On the same machine | `http://localhost:8087/v1` |
| In another Compose project | `http://m87-ai-gateway:8087/v1` |
| Elsewhere, through a proxy or tunnel you operate | `https://<your hostname>/v1` |

Create an application in the console under **Applications** and allow the models it may
use. It shows the key once, with setup snippets for Python, JavaScript, curl and environment variables. To join the shared Docker network from another project:

```yaml
services:
  my-app:
    environment:
      OPENAI_BASE_URL: http://m87-ai-gateway:8087/v1
    networks: [m87-gateway]
networks:
  m87-gateway:
    external: true
```

## One application, one key

Create one application per calling app. The gateway works out the application from the key on
every request, and everything it reports hangs off that: allowed models, limits, logs, usage and
metrics. See [one application's activity](runbooks/projects-and-usage.md#see-one-application).

## Model names

| You send | Routes to | Reported back as |
| --- | --- | --- |
| `qwen3:14b` | The default model's provider, as `ollama:qwen3:14b` | `qwen3:14b` |
| `ollama:qwen3:14b` | That provider and model | `ollama:qwen3:14b` |
| `auto` | The configured default or a task rule | The chosen `provider:model` |

A prefix counts as a provider only when it names a registered adapter, so `qwen3:14b` is
treated as a whole model name. The allowlist always uses the `provider:model` form.
`GET /v1/models` lists both forms for the default provider.

## What is forwarded

Fields the gateway does not model are forwarded unchanged. That covers `tools`,
`tool_choice`, image and other content parts, `n`, `logprobs`, `max_completion_tokens`,
`reasoning_effort` and vendor options. Responses and streams keep their extra fields, such
as `tool_calls`, `reasoning` and `system_fingerprint`. The `user` field is the exception:
it is stored only as a hash and never sent upstream.

The gateway still validates the fields it does model, such as `temperature` and `stop`.
Whether a model honours a forwarded field is up to that model.

Turn on **Strict mode** in **Features** to reject anything except plain text messages and
modelled fields with `422 strict_mode_rejected`. Use it when you want every request to stay
within what the gateway can inspect. Guardrails read message text only, so they do not see
tool arguments or images, and capture records text and marks other parts as omitted.

## When another model answers

If [fallback routes](runbooks/fallback-routes.md) are on and your model fails, another model may answer. The
response's `model` field then names that model, and the `X-Gateway-Fallback` header names the one that failed. Check
`model` if your app depends on which model answered.

## Embeddings

```bash
curl http://localhost:8087/v1/embeddings \
  -H "Authorization: Bearer $GATEWAY_APP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"nomic-embed-text","input":["first text","second text"]}'
```

Embeddings need a named model, because `auto` routes to a chat model. They use the same
allowlist, rate and concurrency limits and logs as chat. They bypass the response cache.
Usage reports them separately, and vectors are never captured.

## Errors

Errors keep the OpenAI shape and add a `request_id` you can search for in **Logs**.

| Status | Code | Meaning |
| --- | --- | --- |
| 401 | `invalid_api_key` | Missing or unknown application key |
| 403 | `model_not_allowed` | The model is not on this application's allowlist |
| 422 | `invalid_request`, `strict_mode_rejected`, `model_required` | The gateway rejected the request |
| 429 | `rate_limit_exceeded`, `concurrency_limit_exceeded`, `queue_full`, `queue_timeout` | A limit was reached; see `Retry-After` |
| 502 | `provider_rejected`, `provider_error` | The provider refused or failed; the message gives its HTTP status |
| 503 | `provider_rate_limited`, `provider_disabled`, `provider_not_configured` | The provider is throttling or is not set up |
| 504 | `provider_timeout` | The provider did not answer within the connection's timeout |

The provider's response body is never returned or logged, because it can contain private
data. The log entry records its HTTP status in `upstream_status`.

## Local models

A large model can take minutes to load. Set the connection timeout in **Providers** to cover
that; the included startup defaults Ollama to 300 seconds.

From a container, the host is `host.docker.internal`. Ollama listens on `127.0.0.1` by
default. Docker Desktop reaches that, but on Linux set `OLLAMA_HOST=0.0.0.0:11434` and
firewall the port to the Docker network. Then use **Test connection** in **Providers**.
