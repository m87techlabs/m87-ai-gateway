"""The gateway's feature list: one definition behind the console and its API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Header, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from m87_gateway.api.errors import GatewayError
from m87_gateway.config import GatewaySettings

from .identity import AdminStore, ReaderStore
from .configuration_service import parse_revision, persist_configuration, revision_etag
from .setup import activate, apply_overrides

router = APIRouter()


@dataclass(frozen=True)
class FeatureField:
    name: str
    label: str
    kind: str = "number"  # number, terms or routes; the console renders a control for each.
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str | None = None
    help: str | None = None


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    summary: str


# The jobs people expect an AI gateway to do. Every feature belongs to exactly one.
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "authentication",
        "Authentication",
        "Each app gets its own key and allowed models, and people sign in to the console.",
    ),
    Capability(
        "routing",
        "Routing",
        "Choose which model answers. Apps keep their code and change only where they point.",
    ),
    Capability(
        "caching",
        "Caching",
        "Answer repeated requests from a stored copy, so they cost nothing and return at once.",
    ),
    Capability(
        "rate_limits",
        "Rate limiting",
        "Stop one app or a traffic spike from overwhelming your models.",
    ),
    Capability(
        "reliability",
        "Reliability",
        "Recover from provider timeouts and failures before your app notices.",
    ),
    Capability(
        "guardrails",
        "Guardrails",
        "Check requests before they reach a model, and reject what you do not allow.",
    ),
    Capability(
        "logging",
        "Logging",
        "See every request: who sent it, which model answered, and what it took.",
    ),
    Capability(
        "monitoring",
        "Monitoring",
        "Track traffic, tokens, latency and errors, here or in your own Grafana.",
    ),
    Capability(
        "cost",
        "Cost tracking",
        "Know how many tokens each app uses. Budgets that cap spend are planned.",
    ),
)


@dataclass(frozen=True)
class Feature:
    id: str
    name: str
    group: str
    summary: str
    read: Callable[[GatewaySettings], dict[str, Any]]
    write: Callable[[dict, bool | None, dict[str, Any], GatewaySettings], None]
    enabled: Callable[[GatewaySettings], bool] | None = None  # None means it cannot be turned off.
    fields: tuple[FeatureField, ...] = ()
    note: str | None = None


def _section(saved: dict, name: str) -> dict:
    return saved.setdefault("controls", {}).setdefault(name, {})


def _write_controls(section: str):
    def write(saved, enabled, values, settings):
        _section(saved, section).update(values)
        if enabled is not None:
            _section(saved, section)["enabled"] = enabled

    return write


def _write_retries(saved, enabled, values, settings):
    retry = _section(saved, "retry")
    retry.update(values)
    attempts = retry.get("max_attempts", settings.retry.max_attempts)
    if enabled is False:
        retry["max_attempts"] = 1
    elif enabled is True and attempts < 2:
        retry["max_attempts"] = 3


def _write_queue(saved, enabled, values, settings):
    limits = _section(saved, "limits")
    limits.update(values)
    depth = limits.get("queue_max_depth", settings.limits.queue_max_depth)
    if enabled is False:
        limits["queue_max_depth"] = 0
    elif enabled is True and depth < 1:
        limits["queue_max_depth"] = 64


def _write_capture(saved, enabled, values, settings):
    if enabled is not None:
        saved["capture_content"] = enabled
    controls = saved.setdefault("controls", {})
    controls.update(values)


def _write_blocklist(saved, enabled, values, settings):
    current = settings.guardrails.blocklist
    saved["blocklist"] = {
        "enabled": current.enabled if enabled is None else enabled,
        "blocked_terms": values.get("blocked_terms", current.blocked_terms),
    }


def _write_routes(saved, enabled, values, settings):
    if "routes" in values:
        saved["routing_rules"] = [
            {"name": f"task-{item['task']}", "when_task": item["task"], "route_to": item["model"]}
            for item in values["routes"]
        ]


def _write_flag(key: str):
    def write(saved, enabled, values, settings):
        if enabled is not None:
            saved[key] = enabled

    return write


def _write_size(saved, enabled, values, settings):
    _section(saved, "guardrails").update(values)


def _write_strict(saved, enabled, values, settings):
    if enabled is not None:
        _section(saved, "compatibility")["strict_requests"] = enabled


def _write_top_controls(saved, enabled, values, settings):
    saved.setdefault("controls", {}).update(values)


FEATURES: tuple[Feature, ...] = (
    Feature(
        "response_cache",
        "Response cache",
        "caching",
        "Return a stored answer for an identical request from the same application.",
        lambda s: {"ttl_seconds": s.cache.ttl_seconds, "max_entries": s.cache.max_entries},
        _write_controls("cache"),
        lambda s: s.cache.enabled,
        (
            FeatureField("ttl_seconds", "Keep answers for", minimum=1, maximum=86400, unit="s"),
            FeatureField("max_entries", "Maximum stored answers", minimum=1, maximum=100000),
        ),
        "Skipped for streams and embeddings. Held in memory, so it clears on restart and on save.",
    ),
    Feature(
        "retries",
        "Automatic retries",
        "reliability",
        "Retry a request when a provider times out, throttles or fails.",
        lambda s: {"max_attempts": s.retry.max_attempts, "backoff_ms": s.retry.backoff_ms},
        _write_retries,
        lambda s: s.retry.max_attempts > 1,
        (
            FeatureField("max_attempts", "Attempts, including the first", minimum=1, maximum=5),
            FeatureField("backoff_ms", "First retry delay", minimum=0, maximum=10000, unit="ms"),
        ),
        "Skipped for streams. A retry can repeat provider work and charges.",
    ),
    Feature(
        "request_queue",
        "Request queue",
        "rate_limits",
        "Hold requests briefly when the concurrency limit is full, instead of rejecting them.",
        lambda s: {
            "queue_max_depth": s.limits.queue_max_depth,
            "queue_max_depth_per_app": s.limits.queue_max_depth_per_app,
            "queue_wait_timeout_seconds": s.limits.queue_wait_timeout_seconds,
        },
        _write_queue,
        lambda s: s.limits.queue_max_depth > 0,
        (
            FeatureField("queue_max_depth", "Maximum queued requests", minimum=0, maximum=10000),
            FeatureField(
                "queue_max_depth_per_app", "Maximum per application", minimum=1, maximum=10000
            ),
            FeatureField(
                "queue_wait_timeout_seconds",
                "Maximum wait",
                minimum=0.01,
                maximum=300,
                step=0.01,
                unit="s",
            ),
        ),
    ),
    Feature(
        "concurrency",
        "Concurrency limit",
        "rate_limits",
        "The most requests this gateway runs at once. Applications can have lower limits.",
        lambda s: {"max_concurrent_requests": s.limits.max_concurrent_requests},
        lambda saved, enabled, values, settings: _section(saved, "limits").update(values),
        None,
        (FeatureField("max_concurrent_requests", "Concurrent requests", minimum=1, maximum=10000),),
    ),
    Feature(
        "strict_mode",
        "Strict mode",
        "guardrails",
        "Reject tools, images and any field the gateway does not model.",
        lambda s: {},
        _write_strict,
        lambda s: s.compatibility.strict_requests,
        (),
        "Off by default, so existing OpenAI clients work by changing only their base URL.",
    ),
    Feature(
        "blocklist",
        "Blocklist",
        "guardrails",
        "Reject requests whose text contains a listed phrase.",
        lambda s: {"blocked_terms": s.guardrails.blocklist.blocked_terms},
        _write_blocklist,
        lambda s: s.guardrails.blocklist.enabled,
        (
            FeatureField(
                "blocked_terms",
                "Blocked phrases",
                kind="terms",
                help="One phrase per line. Matching ignores case.",
            ),
        ),
        "Reads message and embedding text only, not tool arguments or images.",
    ),
    Feature(
        "request_size",
        "Request size limits",
        "guardrails",
        "Reject oversized requests before they reach a provider.",
        lambda s: {
            "max_request_bytes": s.guardrails.max_request_bytes,
            "max_message_chars": s.guardrails.max_message_chars,
        },
        _write_size,
        None,
        (
            FeatureField(
                "max_request_bytes", "Maximum request size", minimum=1, maximum=10485760, unit="B"
            ),
            FeatureField("max_message_chars", "Maximum per message", minimum=1, maximum=1048576),
        ),
    ),
    Feature(
        "task_routing",
        "Task routing",
        "routing",
        "Send model auto to a different model based on the request's task field.",
        lambda s: {
            "routes": [
                {"task": rule.when_task, "model": rule.route_to}
                for rule in s.routing.rules
                if rule.when_task
            ]
        },
        _write_routes,
        None,
        (
            FeatureField(
                "routes",
                "Routes",
                kind="routes",
                help="Each target must also be on the application's allowlist.",
            ),
        ),
    ),
    Feature(
        "content_capture",
        "Input and output capture",
        "logging",
        "Store the text of each request and answer so you can read them in Logs.",
        lambda s: {
            "content_retention_days": s.control_plane.content_retention_days,
            "max_content_chars": s.observability.traffic_log.max_content_chars,
        },
        _write_capture,
        lambda s: s.observability.traffic_log.capture_content,
        (
            FeatureField(
                "content_retention_days", "Keep for", minimum=1, maximum=3650, unit="days"
            ),
            FeatureField("max_content_chars", "Maximum per record", minimum=1, maximum=65536),
        ),
        "Applies to every application. Text is stored unencrypted, after best-effort redaction.",
    ),
    Feature(
        "log_retention",
        "Request log retention",
        "logging",
        "How long request metadata stays in Logs. Usage totals are kept separately.",
        lambda s: {"retention_days": s.control_plane.retention_days},
        _write_top_controls,
        None,
        (FeatureField("retention_days", "Keep for", minimum=1, maximum=3650, unit="days"),),
    ),
    Feature(
        "metrics",
        "Prometheus metrics",
        "monitoring",
        "Publish request, token and latency metrics at /metrics.",
        lambda s: {},
        _write_flag("prometheus_metrics"),
        lambda s: s.observability.prometheus_metrics,
        (),
        "/metrics needs no key, so keep it off the public internet.",
    ),
    Feature(
        "json_logs",
        "Container logs",
        "logging",
        "Write one line of JSON metadata to standard output for each request.",
        lambda s: {},
        _write_flag("json_logs"),
        lambda s: s.observability.json_logs,
    ),
)

# Working features managed on another page of the console, so they stay findable from here.
ELSEWHERE = (
    (
        "application_keys",
        "Application keys",
        "authentication",
        "Give each app its own key, with rotation, expiry and revocation.",
        "applications",
    ),
    (
        "model_access",
        "Allowed models",
        "authentication",
        "Choose which models each application may call.",
        "applications",
    ),
    (
        "default_model",
        "Default model and providers",
        "routing",
        "Connect model servers, and choose what the model name auto means.",
        "providers",
    ),
    (
        "app_limits",
        "Per-application limits",
        "rate_limits",
        "Set requests per minute and concurrent requests for each application.",
        "applications",
    ),
    (
        "request_logs",
        "Request logs",
        "logging",
        "Search and filter requests by application, project and status.",
        "logs",
    ),
    (
        "log_export",
        "Log export",
        "logging",
        "Send request metadata to Loki or a webhook.",
        "export",
    ),
    (
        "usage_dashboards",
        "Usage dashboards",
        "monitoring",
        "Requests, tokens, latency and errors for each application.",
        "overview",
    ),
    (
        "audit_log",
        "Audit log",
        "logging",
        "See who changed what, and who signed in.",
        "audit",
    ),
    (
        "token_usage",
        "Token usage per application",
        "cost",
        "Record the tokens each application uses, as reported by the provider.",
        "overview",
    ),
)

PLANNED = (
    (
        "fallback_routes",
        "Fallback routes",
        "reliability",
        "Try another provider or model when one fails.",
    ),
    (
        "provider_health",
        "Provider health checks",
        "reliability",
        "Stop sending traffic to a failing provider until it recovers.",
    ),
    (
        "load_balancing",
        "Load balancing",
        "routing",
        "Share traffic across several providers or keys.",
    ),
    (
        "token_limits",
        "Token rate limits",
        "rate_limits",
        "Limit tokens per minute, not only requests.",
    ),
    (
        "semantic_cache",
        "Semantic cache",
        "caching",
        "Reuse answers to questions that mean the same thing.",
    ),
    (
        "cache_controls",
        "Per-request cache controls",
        "caching",
        "Let a request skip the cache or set its own lifetime.",
    ),
    (
        "response_policies",
        "Response policies",
        "guardrails",
        "Check and redact model output.",
    ),
    (
        "pii_redaction",
        "Personal data detection",
        "guardrails",
        "Find personal data in requests, and flag, redact or block it.",
    ),
    (
        "budgets",
        "Budgets",
        "cost",
        "Limit spend or tokens per application or project.",
    ),
    (
        "cost_estimates",
        "Cost estimates",
        "cost",
        "Turn token usage into an estimated price per request.",
    ),
)


def _describe(feature: Feature, settings: GatewaySettings) -> dict[str, Any]:
    enabled = feature.enabled(settings) if feature.enabled else True
    return {
        "id": feature.id,
        "name": feature.name,
        "group": feature.group,
        "summary": feature.summary,
        "note": feature.note,
        "status": "on" if enabled else "off",
        "enabled": enabled,
        "toggleable": feature.enabled is not None,
        "values": feature.read(settings),
        "fields": [asdict(item) for item in feature.fields],
    }


class FeatureWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    enabled: bool | None = None
    values: dict[str, Any] = {}


@router.get("/admin/api/features")
async def features(request: Request, store: ReaderStore):
    settings = request.app.state.settings
    items = [_describe(feature, settings) for feature in FEATURES]
    items.extend(
        {
            "id": identifier,
            "name": name,
            "group": group,
            "summary": summary,
            "note": None,
            "status": "planned",
            "enabled": False,
            "toggleable": False,
            "values": {},
            "fields": [],
        }
        for identifier, name, group, summary in PLANNED
    )
    items.extend(
        {
            "id": identifier,
            "name": name,
            "group": group,
            "summary": summary,
            "note": None,
            "status": "on",
            "enabled": True,
            "toggleable": False,
            "link": link,
            "values": {},
            "fields": [],
        }
        for identifier, name, group, summary, link in ELSEWHERE
    )
    sso = getattr(request.app.state, "oidc", None) is not None
    items.append(
        {
            "id": "single_sign_on",
            "name": "Single sign-on",
            "group": "authentication",
            "summary": "Sign in through your identity provider, as an admin or read-only.",
            "note": "Set by the GATEWAY_OIDC_ environment settings, so the console cannot turn it off."
            " The admin key keeps working for recovery.",
            "status": "on" if sso else "off",
            "enabled": sso,
            "toggleable": False,
            "badge": "On" if sso else "Off",
            "values": {},
            "fields": [],
        }
    )
    return JSONResponse(
        {"capabilities": [asdict(item) for item in CAPABILITIES], "items": items},
        headers={"ETag": revision_etag(store)},
    )


@router.put("/admin/api/features/{feature_id}")
async def update_feature(
    feature_id: Annotated[str, Path(max_length=64)],
    payload: FeatureWrite,
    request: Request,
    store: AdminStore,
    if_match: Annotated[str | None, Header()] = None,
):
    feature = next((item for item in FEATURES if item.id == feature_id), None)
    if feature is None:
        raise GatewayError(404, "not_found", "Feature was not found")
    if payload.enabled is not None and feature.enabled is None:
        raise GatewayError(422, "not_toggleable", "This feature cannot be turned off")
    allowed = {item.name for item in feature.fields}
    if set(payload.values) - allowed:
        raise GatewayError(422, "unknown_setting", "Unknown setting for this feature")
    current = request.app.state.settings
    saved = store.runtime_config()
    try:
        feature.write(saved, payload.enabled, payload.values, current)
    except (KeyError, TypeError, AttributeError) as exc:
        raise GatewayError(
            422, "invalid_feature_settings", "Check this feature's settings"
        ) from exc
    try:
        settings = apply_overrides(current, saved)
    except ValidationError as exc:
        location = exc.errors()[0].get("loc", ())
        known = {item.name: item.label for item in feature.fields}
        label = next((known[part] for part in location if part in known), None)
        raise GatewayError(
            422,
            "invalid_feature_settings",
            f"Check {label}" if label else "Check this feature's settings",
        ) from exc
    persist_configuration(
        store,
        saved,
        settings,
        action=f"feature.{feature_id}.updated",
        expected_revision=parse_revision(if_match),
    )
    activate(request, settings)
    store.prune_events()
    return JSONResponse(_describe(feature, settings), headers={"ETag": revision_etag(store)})
