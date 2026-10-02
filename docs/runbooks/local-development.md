# Local development

## Trigger and prerequisites

Use this procedure to prepare a development checkout. Install Python 3.11+ and
Git. A provider is needed for a real chat request, but not for the unit tests.
Console interaction checks additionally use Node 18+ and npm with isolated test
dependencies; these are not installed by gateway users.
Docker can stay disabled for this procedure. See [validation status](../validation.md)
for the separate checks that require a container runtime.

## Procedure

1. Create a virtual environment and install the project:

   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install -e '.[dev]'
   ```

2. Run the baseline checks:

   ```bash
   ruff check src tests scripts examples
   ruff format --check src tests scripts examples
   pytest -q
   python scripts/check_docs.py
   ```

   For console changes, also run:

   ```bash
   npm ci --prefix tests/console
   npm test --prefix tests/console
   ```

   These checks parse console CSS and exercise DOM interactions, project-scoped
   requests, charts, application credential isolation, and lock cleanup. They do
   not verify real browser rendering. Hosted CI runs them with the docs checks.

3. Copy `.env.example` to `.env` only if `.env` does not already exist. In that
   ignored file, set a private `GATEWAY_APP_API_KEY` and select a provider:

   - **Ollama:** set `OLLAMA_BASE_URL=http://localhost:11434`; ensure the configured
     model is installed and the service is reachable from this process.
   - **OpenAI:** set `OPENAI_API_KEY` and
     `GATEWAY_DEFAULT_MODEL=openai:gpt-4.1-mini`; confirm the provider account has
     access to that model or configure another allowed model.

4. Start the gateway, explicitly loading the environment file:

   ```bash
   uvicorn m87_gateway.main:app --env-file .env --host 127.0.0.1 --port 8080
   ```

5. In another terminal, check liveness:

   ```bash
   curl --fail-with-body http://localhost:8080/health
   curl --fail-with-body http://localhost:8080/metrics
   ```

6. Send the authenticated request in [quickstart](../quickstart.md). Use a
   synthetic prompt; a real provider call may consume account quota.

## Success checks

- Tests and lint pass.
- `/health` returns HTTP 200 with `status: ok`.
- An authenticated chat request returns a completion from the chosen provider.
- A request without authorization returns HTTP 401.

The health response does not prove provider readiness. Tests currently mock
provider calls and do not replace the real chat check.

## Recovery

Stop Uvicorn with Ctrl-C. Restore the previous ignored configuration if needed.
For chat failures, follow [provider troubleshooting](provider-troubleshooting.md).
Do not paste `.env`, complete prompts, or unredacted logs into an issue.
