# Release and rollback

## Trigger and prerequisites

Use this procedure to prepare a public preview or stable release. It requires a
reviewed commit, publication permissions, a new version, CI evidence, an available
previous artifact, and the completed [lifecycle gates](../lifecycle.md).

Publishing a release, changing repository visibility, and shipping a package or
container are separate actions. Complete the relevant gates before each action.

## Prepare

1. Choose an unused version. The historical `v0.1.0` tag already exists; do not
   move or recreate it.
2. Update package/API version declarations and the changelog in a reviewed change.
   Record breaking changes, migration steps, known limitations, and support scope.
3. From a clean checkout of the intended commit, install and validate:

   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install -e '.[dev]'
   ruff check src tests scripts examples
   ruff format --check src tests scripts examples
   pytest -q
   python scripts/check_docs.py
   python -m pip wheel --no-deps . --wheel-dir dist
   ```

4. Check [deferred validation](../validation.md) and arrange an on-demand Docker
   session. Follow [container deployment](container-deployment.md) and record health,
   valid/invalid auth, allowed/disallowed models, and a real chat result for each
   advertised provider. Run guardrail and safe-error checks for the declared scope.
5. Review files, package contents, history, tags, and release assets for secrets,
   personal details, local paths, and tool attribution. Review commit metadata as
   well as file contents. If historical findings remain, resolve them through a
   separate history-cleanup or clean-public-repository plan before changing visibility.
6. Confirm a working private security-reporting path, issue templates, and
   dependency update automation. Enable appropriate CI/branch protections when the
   repository's hosting plan permits them. Do not change visibility to bypass a plan limit.

## Publish

1. Commit and push the validated release preparation to `main` using the current
   direct-push workflow; verify CI on that exact commit. Check `git status --short`
   is empty. Do not open a pull request unless explicitly requested.
2. Set a generic project author/committer identity for release metadata.
3. Create a new annotated tag for that exact reviewed commit. Inspect the tag
   before pushing it. `scripts/release-tag.sh` creates and immediately pushes a
   tag; use it only after all release gates and version checks are complete.
4. Publish release notes with the scope, validation environment, known limitations,
   upgrade steps, and artifact checksums when artifacts are distributed.
5. Publish only artifacts built from the tagged commit. Retain the previous
   verified version and its matching configuration.

## Success checks

- Tag, release notes, package/API versions, and artifacts agree.
- A clean installation from the published artifact passes the quickstart.
- Advertised providers/deployments have recorded smoke-check evidence.
- The security-reporting path and documentation links work for the intended audience.

## Rollback

Deploy the previous verified image/package with its matching configuration and
rerun auth, health, and chat checks. Preserve release tags and publish a corrective
patch; do not silently replace released artifacts. If a release is unsafe, mark
it accordingly and document the supported replacement.

SQLite schema versions and additive migration are implemented. Preserve the local
master key and operator key with the database. Restore a pre-upgrade encrypted
backup into a fresh directory for rollback; never assume an older binary can read
a migrated database. Distinct-version rollback remains a release gate.

## Automated development previews

Successful main CI runs publish a tested Linux amd64 image with immutable commit
and moving preview tags, and retain native ZIPs/checksums and Compose in a commit
prerelease. These are development previews, distinct from reviewed stable/public
releases. See [container publication](container-deployment.md). Publication follows
all source/docs/native/container jobs; failed runs do not advance the preview.
Repository/package visibility is preserved. Preview downloads last until deletion;
CI artifact downloads expire independently.
