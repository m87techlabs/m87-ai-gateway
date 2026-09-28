# Security policy

## Reporting vulnerabilities

Do not disclose vulnerabilities in public issues. Use the existing project
security mailbox:

```text
m87admin@m87techlabs.com
```

If GitHub private vulnerability reporting is enabled, the repository Security tab
provides another private reporting path. Verify reporting availability before a
public release.

Include the affected version/commit, impact, and a minimal reproduction. Remove
credentials, personal data, and real prompt content. Share sensitive reproduction
material only through the agreed private channel.

## Supported versions

The project is in early development. Fixes target the latest released version;
there is no long-term support commitment for older versions. A historical tag
does not establish production readiness. See the [lifecycle](docs/lifecycle.md).

## Security design

See [security architecture and current limits](docs/security.md). The current
gateway has app keys and requested-model authorization; several controls remain
planned. Follow [incident response](docs/runbooks/incident-response.md) for an
operational incident and [configuration changes](docs/runbooks/configuration-changes.md)
for credential rotation.
