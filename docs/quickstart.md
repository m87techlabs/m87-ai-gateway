# Quickstart

## Choose a setup option

- Download a portable Windows/Linux preview from
  [preview releases](https://github.com/m87techlabs/m87-ai-gateway/releases), then
  follow [workstation distribution](runbooks/workstation-distribution.md).
- With Docker already running, follow [container deployment](runbooks/container-deployment.md).
  Pull the image or use the provided Compose file; no source build or `.env` is required.
- Developers can use [local source setup](runbooks/local-development.md).

The Docker image exposes the included console at **http://localhost:8087**.
Retrieve its private operator key using the container runbook, connect your
inference service in Setup, select a model, and create an application key.
Provider keys are managed in the gateway. Existing inference/cloud access is a
prerequisite; the gateway does not bundle an LLM. Private previews require authorized
repository/package access until publication review is complete.

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
You can also send the request through the console's API tester.

## Inspect and integrate

Enable gateway-wide input/output capture in Setup if needed, then inspect Logs,
request IDs, tokens and project usage. Configure limits, cache, retries and
retention in Controls. Keep operator keys separate from application keys.
For a calling application, use [the chat sample](../examples/chat_app/README.md).

- [Provider troubleshooting](runbooks/provider-troubleshooting.md)
- [Traffic logging](runbooks/traffic-logging.md)
- [Worker-to-local inference](integrations/worker-local-inference.md)
- [Configuration and limitations](configuration.md)
- [Roadmap and release readiness](roadmap.md)
