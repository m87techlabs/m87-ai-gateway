# What the gateway does

M87 AI Gateway sits between your apps and your models. You change your app's base URL and key, and the
gateway takes on the jobs below. Each one has its own page under **Features** in the console, showing what
is on and what you can change.

Status terms follow the [documentation conventions](README.md#read-implementation-status).

| Job | What it does for you | Works today | Planned |
| --- | --- | --- | --- |
| [Authentication](#authentication) | Controls who can call which model | Application keys, allowed models, console sign-on | |
| [Routing](#routing) | Chooses the model that answers | Providers, default model, task routing | Load balancing |
| [Caching](#caching) | Answers repeats without calling a model | Exact-match cache | Semantic cache, per-request controls |
| [Rate limiting](#rate-limiting) | Stops one app or a spike overwhelming your models | Requests per minute, concurrency, queue | Token limits |
| [Reliability](#reliability) | Recovers from provider failures | Automatic retries | Fallback routes, provider health checks |
| [Guardrails](#guardrails) | Rejects requests you do not allow | Size limits, blocklist, Strict mode | Response policies, personal data detection |
| [Logging](#logging) | Shows every request | Request logs, optional capture, export, audit log | |
| [Monitoring](#monitoring) | Tracks traffic and health over time | Console dashboards, Prometheus metrics, Grafana dashboards, alerts | |
| [Cost tracking](#cost-tracking) | Shows what each app uses | Tokens per application and model | Cost estimates, budgets |

## Authentication

- **Application keys.** Each app gets its own key, with rotation, expiry and revocation. Everything the app
  does is reported under its name.
- **Allowed models.** Each application can call only the models you list.
- **Console sign-in.** People sign in with the admin key or through
  [single sign-on](runbooks/single-sign-on.md), as an admin or read-only. The audit log names them.

## Routing

- **One API.** Apps use the OpenAI API, so most need only a new base URL. See
  [connect your app](connect-your-app.md).
- **Providers.** OpenAI, Ollama and other OpenAI-compatible services.
- **Default model and task routing.** The model name `auto` uses your default, or a different model chosen
  by the request's `task` field.

## Caching

The response cache returns a stored answer to an identical request from the same application. Cache hits use
no provider tokens and return at once. You set how long answers are kept and how many are stored, and you can
clear it from the console.

It matches exactly, so a reworded question is a miss. It skips streams and embeddings. It is held in memory,
so it clears on restart and when settings are saved.

## Rate limiting

- **Per application.** Requests per minute and concurrent requests.
- **Across the gateway.** A concurrency limit on everything running at once.
- **Request queue.** Holds requests briefly when the limit is full, instead of rejecting them.

Limits are counted per process and by requests, not by tokens.

## Reliability

Automatic retries cover provider timeouts, throttling and failures. Streams are not retried, and a retry can
repeat provider work and charges. When a client disconnects, the gateway stops the upstream request, so a
local model stops generating.

## Guardrails

- **Request size limits** reject oversized requests before they reach a provider.
- **Blocklist** rejects requests containing a phrase you list.
- **Strict mode** rejects tools, images and any field the gateway does not model.

These check requests, not responses. The blocklist reads message and embedding text, not tool arguments or
images, unless Strict mode rejects those requests first.

## Logging

- **Request logs** record who called, which model answered, tokens, latency and status, without the text. Filter
  by application, project and status.
- **Input and output capture** stores the text as well. It is off by default, covers every application when on,
  and is stored unencrypted after best-effort redaction.
- **Log export** sends metadata, never text, to Loki or a webhook.
- **Audit log** records configuration changes and sign-ins, by person.

## Monitoring

The console shows requests, tokens, latency and errors for each application. For longer history and alerts,
the gateway publishes Prometheus metrics and includes Grafana dashboards and alert rules. See
[how data reaches Grafana](grafana-data-flow.md).

## Cost tracking

The gateway records the tokens each application and model uses, as the provider reports them. Cache hits do not
count. It does not yet convert tokens to a price or stop an app that spends too much.

## What the gateway is not

It runs as one instance on SQLite, so limits and the cache are per process, and it should not run as several
replicas against one store yet. See the [roadmap](roadmap.md), the [backlog](backlog.md) and
[what has been verified](validation.md).
