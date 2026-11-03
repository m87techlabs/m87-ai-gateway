# Quickstart

## Choose a setup option

- With Docker running, follow the [README](../README.md#start-it) or
  [container deployment](runbooks/container-deployment.md). This is the recommended option.
- Developers can use [local source setup](runbooks/local-development.md).

The Docker image exposes the included console at **http://localhost:8087**.
Retrieve its private operator key using the container runbook, connect your
inference service in **Providers**, select a model, and create an application key.
Provider keys are managed in the gateway. Existing inference/cloud access is a
prerequisite; the gateway does not bundle an LLM.

## Check and send a request

```bash
curl --fail-with-body http://localhost:8087/health
curl --fail-with-body http://localhost:8087/ready
read -r -s -p "Gateway application key: " GATEWAY_APP_KEY
printf '\n'
curl --fail-with-body http://localhost:8087/v1/chat/completions \
  -H "Authorization: Bearer ${GATEWAY_APP_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Explain a network gateway in one sentence."}]}'
unset GATEWAY_APP_KEY
```

`/health` checks the process. `/ready` initially returns 503 until setup passes;
it checks configuration, credentials and storage, not provider connectivity.
A real request can consume provider quota. Use synthetic content for setup tests.
You can also send the request through the console's Playground.

## Inspect and integrate

Enable gateway-wide input/output capture in **Features** if needed, then inspect Logs,
request IDs, tokens and project usage. Configure limits, cache, retries and
retention in **Features**. Keep operator keys separate from application keys.
To point an existing application at it, see [connect your app](connect-your-app.md).

- [Provider troubleshooting](runbooks/provider-troubleshooting.md)
- [Traffic logging](runbooks/traffic-logging.md)
- [Worker-to-local inference](integrations/worker-local-inference.md)
- [Configuration and limitations](configuration.md)
- [Roadmap and release readiness](roadmap.md)
