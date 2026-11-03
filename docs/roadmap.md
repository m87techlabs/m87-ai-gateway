# Roadmap

The gateway is for developers who want one place between their apps and any LLM, local or hosted:
quick to start, easy to change, and fully under their control. Work is judged by time to first request
and by how little a calling app has to change. Releases follow readiness rather than dates.

## Released

**0.1.1, the first release.** Drop-in OpenAI-compatible API with chat, streaming and embeddings. Ollama,
OpenAI and OpenAI-compatible adapters. Per-application keys, reporting and limits. A web console with a
Features page. Docker Compose packaging, with optional monitoring. See the [changelog](../CHANGELOG.md)
and [what has been verified](validation.md).

## Next

### 0.2: ready for a server

Run safely on a cloud host such as EC2.

- A Compose profile with TLS through a reverse proxy.
- `/metrics` that needs authentication.
- Throttling for admin key attempts, and a `Secure` session cookie behind a TLS proxy.
- A runbook verified on a real cloud host.

**Done when:** someone can deploy to a fresh server from the runbook, with no unauthenticated
operator surface exposed.

### 0.3: more providers

- Named connections, so several providers of one type can run at once.
- A live check against OpenAI and at least one other compatible provider.
- An Anthropic adapter.
- Fallback routes between providers.

**Done when:** each advertised provider has a recorded live check and passes shared contract tests.

### 0.4: spend and safety

- Budgets per application and project, with cost estimates.
- Response policies, and guardrails that cover tool arguments and images.
- Provider health and circuit breaking.

**Done when:** a hard budget stops traffic at its limit, and policies are tested on complete and
streamed responses.

### Later

AWS Bedrock, Azure OpenAI and Vertex AI adapters, shared state for several gateway instances, operator
roles, and tracing. See the [backlog](backlog.md) for scope and acceptance criteria.

### 1.0: stable contract

Stable API, configuration and adapter contracts, with documented migration and support. See the
[lifecycle](lifecycle.md).

## Not planned

These were considered and dropped, to keep one clear way to run the gateway:

- Portable Windows or Linux installers, OS services and code signing. Docker covers these platforms.
- A console that starts or manages containers. Controlling Docker needs the Docker socket, which is
  effectively root on the host. Optional services are Compose profiles instead.
- Kubernetes and Terraform examples, until someone needs them and they can be tested.

## Provider support

| Provider | Adapter | Status |
| --- | --- | --- |
| Ollama | `ollama` | Verified live |
| OpenAI | `openai` | Implemented; live check pending |
| OpenAI-compatible servers, such as vLLM | `openai_compatible` | Implemented; live check pending |
| Anthropic | Planned | 0.3 |
| AWS Bedrock, Azure OpenAI, Google Vertex AI | Planned | Later |

Hosting the gateway on a cloud and calling that cloud's models are separate goals.
