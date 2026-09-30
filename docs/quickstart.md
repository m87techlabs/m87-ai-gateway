# Quickstart

## Requirements

- Docker with Compose, or Python 3.11+ for local development.
- A reachable Ollama instance with the configured model installed, or an OpenAI
  account with access to the selected model.
- A private app key chosen for this gateway.

## Configure

Copy `.env.example` to `.env` if no local file exists, then edit it privately.

| Path | Set in `.env` |
| --- | --- |
| Ollama in Docker | `GATEWAY_DEFAULT_MODEL=ollama:llama3` and a container-reachable `OLLAMA_BASE_URL` |
| OpenAI | `OPENAI_API_KEY` and `GATEWAY_DEFAULT_MODEL=openai:gpt-4.1-mini` |
| Both | `GATEWAY_APP_API_KEY` to your private app key |

For another model, update the route and allowlist together. The example default
is Ollama; adding an OpenAI key alone does not change the route.

The example Ollama URL uses `host.docker.internal`, mapped by Compose. On Linux,
the host service needs a listener reachable from the Docker network. See the
[container runbook](runbooks/container-deployment.md) for details.

## Start

```bash
docker compose config --quiet
docker compose up --build -d
curl --fail-with-body http://localhost:8080/health
```

Expect HTTP 200 with `status: ok`. The port is published on host loopback.
Health checks only the gateway process, not provider access.

Confirm that aggregate metrics are available on the operator network:

```bash
curl --fail-with-body http://localhost:8080/metrics
```

## Send a request

In Bash, enter the same app key configured in `.env`:

```bash
read -r -s -p "Gateway app key: " GATEWAY_APP_KEY
printf '\n'
curl --fail-with-body http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer ${GATEWAY_APP_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "Explain a network gateway in one sentence."}
    ]
  }'
unset GATEWAY_APP_KEY
```

Expect a chat completion containing an assistant message. A real provider call
may consume quota. Use synthetic prompts for setup checks.

Verify missing auth fails:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}'
```

Expect `401`.

## Next steps

- [Local Python development](runbooks/local-development.md)
- [Provider troubleshooting](runbooks/provider-troubleshooting.md)
- [Private LLM traffic logging](runbooks/traffic-logging.md)
- [Worker-to-local inference](integrations/worker-local-inference.md)
- [Configuration and limitations](configuration.md)
- [Roadmap and release readiness](roadmap.md)
