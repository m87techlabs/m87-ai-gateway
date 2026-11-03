# Release

How to publish a version. Pushing a `v*` tag does the rest.

## What a release produces

A version tag makes CI run every check, then publish:

- Images for amd64 and arm64 at `ghcr.io/m87techlabs/m87-ai-gateway`, tagged with the commit,
  the version (`0.1.1`), the minor line (`0.1`) and `latest`.
- A GitHub release, with notes taken from the changelog and a `docker-compose.yml` pinned to that image.

Pushes to `main` publish only the commit tag and `preview`. `latest` moves only on a release.

## Prepare

1. Choose an unused version. Do not move or recreate an existing tag. `v0.1.0` is the historical scaffold.
2. Set the version in `pyproject.toml` and `src/m87_gateway/__init__.py`. CI refuses a tag that does
   not match them, or that has no changelog section.
3. Move the changelog's `Unreleased` notes under `## [x.y.z] - YYYY-MM-DD`. Include upgrade steps,
   breaking changes and known limitations. This text becomes the release notes.
4. Run the [lifecycle gates](../lifecycle.md#release-gates) and update [validation](../validation.md).
5. Scan for secrets:

   ```bash
   gitleaks git --no-banner --redact .
   ```

6. Commit, push to `main`, and confirm CI passes on that commit.

## Publish

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
gh run watch
```

## Check

Run the quickstart the way a new user would, in an empty folder, while signed out of the registry:

```bash
docker logout ghcr.io
curl -fsSLO https://github.com/m87techlabs/m87-ai-gateway/releases/latest/download/docker-compose.yml
docker compose up -d
docker compose exec m87-ai-gateway cat /data/gateway/admin.key
```

Sign in, connect a provider, create an application and send a request. Confirm that the version in
`docker compose exec m87-ai-gateway m87-gateway --version` matches, then clean up with
`docker compose down --volumes`.

## If something is wrong

Fix it in a new patch version. Do not move a published tag or overwrite a version's image. If a
release is harmful, mark it clearly in its notes, or delete the GitHub release so that `latest` falls
back to the previous one, and publish the fix.

For a failed tag run, nothing is released until the `release` job passes. Fix the cause, then use
the next patch version if images were already published.
