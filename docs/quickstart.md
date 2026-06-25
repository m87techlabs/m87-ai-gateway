# Quickstart

## Requirements

- Docker
- Docker Compose
- Optional: OpenAI API key
- Optional: Ollama running locally

## Start locally

```bash
cp .env.example .env
docker compose up --build
```

## Health check

```bash
curl http://localhost:8080/health
```

## Chat completion request

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer demo-app-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "Explain AWS VPC in simple terms"}
    ]
  }'
```
