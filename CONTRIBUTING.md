# Contributing

## Working agreement

Read [AGENTS.md](AGENTS.md), the [design](docs/design.md), and the
[roadmap](docs/roadmap.md) before making a substantial change. Keep scope focused
on gateway capabilities and label implementation status accurately.

Use generic project examples and identities. Do not add personal contact details,
workstation paths, credentials, private prompts, or generated-tool attribution
to repository content or new commits.

For this repository, configure a project identity locally:

```bash
git config --local user.name "M87 Gateway Maintainers"
git config --local user.email "maintainers@example.invalid"
```

The email is a reserved example address, not a support mailbox. Account-level
hosting records and existing Git history are separate from new commit metadata.

## Development

Follow [local development](docs/runbooks/local-development.md). Before submitting:

```bash
ruff check src tests scripts
pytest -q
python scripts/check_docs.py
```

When packaging changes, also build a wheel. Use synthetic data and mocked
providers in normal tests; live provider checks must be deliberate and opt-in.

## Branches and commits

Use focused branches: `feature/<name>`, `fix/<name>`, or `docs/<name>`.
Use Conventional Commits, for example:

- `feat: add provider error normalization`
- `fix: authorize resolved model routes`
- `docs: add gateway operations runbooks`

Push the branch and open a pull request. Require passing CI and review before
merging when hosting settings support enforcement. Prefer squash merging a
focused change. Do not force-push the default branch or move published tags.

## Pull requests

Explain the user-visible result, important design choices, validation performed,
and any remaining limitations. Update the changelog, configuration examples,
roadmap/support claims, and applicable runbooks together.

Use Mermaid for flows or boundaries that benefit from a diagram. Preserve existing
documentation entry points. A provider contribution needs capability documentation,
contract tests, credential guidance, and troubleshooting steps.

See [lifecycle](docs/lifecycle.md) for release gates and [SECURITY.md](SECURITY.md)
for private vulnerability reporting.
