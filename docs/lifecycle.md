# Project lifecycle

## Status and release intent

The project is in early release. Each version declares what it supports and states its limits. Public
releases may precede full provider or cloud coverage.

`v0.1.1` is the first real release. The historical `v0.1.0` tag describes the initial scaffold and stays
in place. Read the [roadmap](roadmap.md) for what comes next.

```mermaid
stateDiagram-v2
    [*] --> Proposed
    Proposed --> Designed: Scope and acceptance criteria
    Designed --> Implemented: Code and documentation
    Implemented --> Validated: Tests and operational evidence
    Validated --> Preview: Public release gates pass
    Preview --> Stable: Compatibility and support commitments
    Stable --> Deprecated: Replacement and migration guide
    Deprecated --> Retired: Announced support window ends
    Preview --> Designed: Feedback requires changes
```

## Feature lifecycle

1. Describe the user problem, affected contract, and success criteria in an issue.
2. Record substantial design choices and update the roadmap status.
3. Implement a focused change with tests, configuration examples, and docs.
4. Review behavior, failure handling, privacy, and operational implications.
5. Record validation against the exact commit and supported environment.
6. Update the changelog, commit and push to `main`, then verify hosted CI.
7. Publish only after release gates pass; collect feedback for the next milestone.

A new provider additionally needs shared contract tests, an opt-in live smoke
check, a capability table, credential guidance, and a troubleshooting procedure.

## Release gates

| Gate | Evidence required |
| --- | --- |
| Core path | Clean setup, valid auth, allowed route, real provider response, and documented errors |
| Policy | Negative checks for auth, model access, configured guardrails, and any advertised limits |
| Compatibility | Explicit supported request/response features and provider matrix |
| Operations | Health behavior, safe logs, required metrics, configuration change and rollback procedures |
| Packaging | Image build, container smoke check and a clean quickstart from the published image |
| Documentation | Quickstart, configuration, design, glossary, lifecycle, stack, roadmap, and applicable runbooks agree |
| Repository hygiene | Generic examples and project identity; no personal contact details, secrets, local paths, or tool attribution in new content |
| History review | Review tracked history, tags, release assets, and commit metadata before changing visibility; resolve findings deliberately |
| Governance | License, contribution guide, code of conduct, private vulnerability reporting, and issue/PR templates are usable |
| Automation | Required CI checks pass; dependency and action updates are configured |
| Release | Version/changelog agree, tag is new, release notes state limitations, rollback target is available |

Never imply that a planned cloud integration passed these gates.

## Git and review policy

- Commit and push directly to `main` for the current development workflow.
- Do not open pull requests unless explicitly requested; temporary branches are optional.
- Use Conventional Commits describing the change and its reason.
- Use a generic project identity for new commits; keep personal identity and
  generated-tool attribution out of commit messages and repository content.
- Run relevant local checks before pushing and verify hosted CI afterward.
- Fetch and preserve remote changes; never force-push the default branch.
- Preserve existing tags and published history. Any history cleanup needs a
  separate, reviewed plan because it changes commit identifiers and downstream clones.

## Repository settings

The repository and its image are public. Dependency alerts and automated security fixes are on, and
workflow permissions are read-only by default. Private vulnerability reporting is on. Pushes go directly
to `main` under the current workflow, with hosted CI verified afterward.

## Compatibility and maintenance

- `0.x` releases may change APIs/configuration, but document breaking changes and migration steps.
- `1.x` establishes the documented API, configuration, and adapter compatibility contract.
- Patch releases fix compatible defects; minor releases add compatible behavior;
  major releases may remove or change established contracts.
- Until a broader policy is published, fixes target the latest released version;
  do not promise long-term support for older versions.
- Deprecations must name a replacement, migration procedure, and planned removal release.

## Deployment lifecycle

```mermaid
flowchart LR
    Build[Build immutable artifact] --> Stage[Configure staging]
    Stage --> Check[Run health and chat checks]
    Check --> Deploy[Deploy approved version]
    Deploy --> Observe[Observe errors and latency]
    Observe --> Accept[Accept deployment]
    Observe --> Rollback[Restore previous artifact and config]
```

Use the [release runbook](runbooks/release.md) to publish and the
[configuration runbook](runbooks/configuration-changes.md) for runtime changes.
