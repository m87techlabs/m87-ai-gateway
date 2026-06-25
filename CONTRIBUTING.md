# Contributing

Thank you for your interest in contributing to M87 AI Gateway.

## Development principles

- Keep the gateway lightweight and self-hostable.
- Prefer clear interfaces over provider-specific shortcuts.
- Do not log secrets, API keys, raw authorization headers, or sensitive credentials.
- Keep public APIs documented and backward-compatible where possible.

## Branch naming

Use descriptive branches:

```text
feature/openai-provider
feature/prometheus-metrics
fix/auth-header-validation
docs/quickstart
```

## Commit style

Use Conventional Commits:

```text
feat: add OpenAI-compatible chat endpoint
fix: validate missing authorization header
docs: add local quickstart
chore: add Docker Compose
test: add auth middleware tests
refactor: extract provider interface
security: redact API key from logs
```

## Pull requests

Before opening a pull request:

1. Run tests.
2. Run linting.
3. Update documentation if behavior changes.
4. Update `CHANGELOG.md` for notable changes.
