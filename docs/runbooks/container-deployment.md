# Container deployment

## Trigger and prerequisites

Use this procedure for a single-instance Docker Compose deployment. Install
Docker with Compose. Have a provider endpoint/model and credentials available.
For development, access the published port through the local machine. A shared
deployment requires TLS ingress and an explicit network/access policy.

Docker is enabled on demand in the development environment. Arrange a session
only when the checks in [validation status](../validation.md) are needed; batch
related checks and stop this project's test deployment afterward. Enabling or
stopping Docker Desktop itself remains an operator action.

## Procedure

1. Follow [quickstart](../quickstart.md) to prepare the ignored `.env` file and
   choose a default route. Replace the demonstration app key before sharing access.
2. For Ollama, set `OLLAMA_BASE_URL` to an address reachable from the **container**:
   - The Compose file maps `host.docker.internal` to the Docker host gateway.
   - On Linux, a provider bound only to host loopback may still be unreachable.
     Configure a private reachable listener and firewall policy, or use an
     Ollama service on the same Docker network and its service name.
   - `localhost` inside the gateway container refers to the gateway container.
3. Validate Compose syntax without printing interpolated values:

   ```bash
   docker compose config --quiet
   ```

4. Build and start:

   ```bash
   docker compose up --build -d
   docker compose ps
   curl --fail-with-body http://localhost:8080/health
   ```

5. Run the authenticated quickstart request and the missing-auth check.
6. Inspect recent logs locally:

   ```bash
   docker compose logs --tail=100 m87-ai-gateway
   ```

## Success checks

The container stays running, health returns 200, valid chat succeeds, and missing
auth returns 401. Record the image/commit and configuration revision without
recording secrets. Metrics and readiness are not implemented yet.

## Recovery and rollback

- If startup fails, inspect build/startup logs and restore the previous configuration.
- If only chat fails, use [provider troubleshooting](provider-troubleshooting.md).
- Recreate the service after environment changes:

  ```bash
  docker compose up -d --force-recreate
  ```

- For an application rollback, build or deploy the previously verified commit/image
  from a separate checkout with its matching configuration. Recheck health and chat.
- `docker compose down` stops this Compose deployment; it interrupts traffic.

The current Compose file builds local source. It does not select a published,
immutable image automatically. Cloud rollout procedures remain planned.
