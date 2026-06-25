# Security

## Design goals

- Keep provider credentials server-side.
- Prevent direct frontend exposure of LLM provider keys.
- Authenticate calling apps.
- Authorize apps by allowed models and future policy rules.
- Avoid logging secrets.
- Add guardrail checks before provider invocation.

## Initial controls

- Bearer API key authentication
- App-level model allowlist
- Basic blocklist guardrail
- Structured audit logs with secret redaction
