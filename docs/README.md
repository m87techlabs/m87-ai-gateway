# Documentation

M87 AI Gateway is a self-hosted gateway for developers, run with Docker Compose. Start with the
[quickstart](quickstart.md) or [run with Docker](runbooks/container-deployment.md).

## Start here

| Page | Use it to |
| --- | --- |
| [Quickstart](quickstart.md) | Run the gateway and send a request |
| [Run with Docker](runbooks/container-deployment.md) | Start, stop, back up and upgrade |
| [Guided setup](runbooks/guided-setup.md) | Connect a provider and create an application |
| [Connect your app](connect-your-app.md) | Base URLs, model names, forwarded fields, embeddings and errors |
| [Runbooks](runbooks/README.md) | Find a procedure |

## Reference

| Page | Covers |
| --- | --- |
| [Configuration](configuration.md) | Settings and environment variables |
| [Control plane](control-plane.md) | The console and its API |
| [Observability](observability.md) | Logs, metrics and exports |
| [Security](security.md) | Security model and current limits |
| [Adapters](adapters.md) | Writing a provider adapter |
| [Backend adapters](backend-adapters.md) | Storage adapters |
| [Worker to local inference](integrations/worker-local-inference.md) | Calling a home GPU from a Cloudflare Worker |
| [Glossary](glossary.md) | Shared terms |

## Project

| Page | Covers |
| --- | --- |
| [Roadmap](roadmap.md) | What comes next, and what is not planned |
| [Backlog](backlog.md) | Scope and acceptance criteria for planned work |
| [What has been verified](validation.md) | What was and was not checked |
| [Design](design.md) | Product boundaries and decisions |
| [Architecture](architecture.md) | Request path and components |
| [Backend architecture](backend-architecture.md) | Storage design |
| [Stack](stack.md) | Technology choices |
| [Lifecycle](lifecycle.md) | Release gates and compatibility |
| [Release notes](releases/README.md) | What changed in each version, and how to upgrade |
| [Changelog](../CHANGELOG.md) | A short list of changes |

## Read implementation status literally

- **Implemented:** present in the source; verification limits are called out.
- **Partial:** some behavior exists, with specific gaps listed.
- **Planned:** a design target without a supported implementation.
- **Verified:** evidence identifies the version, environment, and check performed.

A configuration field does not establish support. Compatibility claims need tests, documentation and
a runbook.
