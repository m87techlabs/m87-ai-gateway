# Security Policy

## Reporting vulnerabilities

Please do not open public GitHub issues for security vulnerabilities.

Report security concerns by emailing:

```text
m87admin@m87techlabs.com
```

Include:

- Affected version or commit
- Description of the issue
- Steps to reproduce
- Potential impact
- Suggested remediation, if known

## Security design goals

M87 AI Gateway should:

- Avoid logging secrets or authorization headers.
- Support per-app authentication and authorization.
- Support model allowlists.
- Provide structured audit logs.
- Make guardrail behavior explicit and configurable.
