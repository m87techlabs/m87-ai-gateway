"""Console single sign-on and the read-only role, against a fake provider with real signatures."""

import logging
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from m87_gateway.cli import local_settings
from m87_gateway.config.settings import OidcConfig
from m87_gateway.control.identity import ADMIN_KEY_PRINCIPAL, issue_session, read_session
from m87_gateway.control.oidc import CALLBACK_PATH, STATE_COOKIE, OidcClient
from m87_gateway.main import HideSignInCode, create_app
from test_runtime import completion

KEY = "sso-test-admin-key-with-enough-length"
ADMIN = {"Authorization": f"Bearer {KEY}"}
CONSOLE = {"X-Gateway-Console": "1"}
ISSUER = "https://idp.example.test/realms/lab"
CLIENT_ID = "m87-gateway"
SECRET = "client-secret-value-for-tests"
PUBLIC_URL = "http://localhost"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def signed(claims: dict, key=SIGNING_KEY, algorithm="RS256", kid="signing-key") -> str:
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


class Provider:
    """Answers discovery, keys and the token endpoint. Tests adjust what the tokens say."""

    def __init__(self):
        self.roles = ["admin"]
        self.username = "alice"
        self.id_overrides = {}
        self.access_overrides = {}
        self.id_key = SIGNING_KEY
        self.id_algorithm = "RS256"
        self.nonce = None
        self.down = False
        self.token_requests = []
        self.discovery_issuer = ISSUER

    def claims(self, **extra):
        now = int(time.time())
        return {"iss": ISSUER, "sub": "user-1", "iat": now, "exp": now + 300, **extra}

    def tokens(self):
        identity = self.claims(
            aud=CLIENT_ID, azp=CLIENT_ID, nonce=self.nonce, preferred_username=self.username
        )
        access = self.claims(
            aud="account", azp=CLIENT_ID, resource_access={CLIENT_ID: {"roles": self.roles}}
        )
        return {
            "id_token": signed({**identity, **self.id_overrides}, self.id_key, self.id_algorithm),
            "access_token": signed({**access, **self.access_overrides}),
            "token_type": "Bearer",
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("provider is down")
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": self.discovery_issuer,
                    "authorization_endpoint": f"{ISSUER}/auth",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                    "end_session_endpoint": f"{ISSUER}/logout",
                },
            )
        if request.url.path.endswith("/jwks"):
            jwk = jwt.algorithms.RSAAlgorithm.to_jwk(SIGNING_KEY.public_key(), as_dict=True)
            return httpx.Response(
                200, json={"keys": [{**jwk, "kid": "signing-key", "use": "sig", "alg": "RS256"}]}
            )
        if request.url.path.endswith("/token"):
            self.token_requests.append(request)
            return httpx.Response(200, json=self.tokens())
        return httpx.Response(200, json=completion("ok"))


@pytest.fixture
def provider():
    return Provider()


@pytest.fixture
def make_gateway(tmp_path, monkeypatch, provider):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", KEY)
    monkeypatch.setenv("GATEWAY_OIDC_CLIENT_SECRET", SECRET)
    original = httpx.AsyncClient

    def client(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(provider))
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    def build(capture=False, **oidc):
        settings = local_settings(tmp_path)
        settings.observability.json_logs = False
        settings.providers.ollama.enabled = True
        settings.routing.default_model = "ollama:test"
        settings.observability.traffic_log.capture_content = capture
        settings.control_plane.oidc = OidcConfig(
            **{"issuer": ISSUER, "client_id": CLIENT_ID, "public_url": PUBLIC_URL, **oidc}
        )
        return create_app(settings)

    return build


@pytest.fixture
def gateway(make_gateway):
    with TestClient(make_gateway(), base_url="http://localhost", follow_redirects=False) as browser:
        yield browser


def sign_in(browser, provider, state=None):
    """Walks the browser's side of the flow, and hands the provider the nonce it was sent."""
    started = browser.get("/admin/auth/login")
    assert started.status_code == 302
    query = parse_qs(urlsplit(started.headers["location"]).query)
    if provider.nonce is None:
        provider.nonce = query["nonce"][0]
    return browser.get(
        CALLBACK_PATH, params={"code": "one-time-code", "state": state or query["state"][0]}
    )


def rejected(response, reason: str) -> bool:
    return response.status_code == 302 and response.headers["location"].endswith(
        f"sign_in_error={reason}"
    )


def signed_in_as(browser, role):
    session = browser.get("/admin/api/session")
    assert session.status_code == 200
    assert session.json()["role"] == role
    return session.json()


# ---- The sign-in flow


def test_authorization_request_uses_pkce_and_exact_redirect(gateway):
    location = gateway.get("/admin/auth/login").headers["location"]
    query = parse_qs(urlsplit(location).query)
    assert location.startswith(f"{ISSUER}/auth?")
    assert query["response_type"] == ["code"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [f"{PUBLIC_URL}{CALLBACK_PATH}"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0] and query["nonce"][0] and query["state"][0]
    assert SECRET not in location


def test_redirect_ignores_the_host_header(gateway):
    location = gateway.get("/admin/auth/login", headers={"Host": "evil.example"}).headers[
        "location"
    ]
    assert parse_qs(urlsplit(location).query)["redirect_uri"] == [f"{PUBLIC_URL}{CALLBACK_PATH}"]


@pytest.mark.parametrize("role,expected", [("admin", "admin"), ("readonly", "readonly")])
def test_sign_in_maps_the_two_roles(gateway, provider, role, expected):
    provider.roles = [role]
    response = sign_in(gateway, provider)
    assert response.status_code == 302 and response.headers["location"] == "/admin"
    session = signed_in_as(gateway, expected)
    assert session["actor"] == "alice" and session["method"] == "sso"
    form = parse_qs(provider.token_requests[0].content.decode())
    assert form["code_verifier"][0] and form["grant_type"] == ["authorization_code"]
    assert provider.token_requests[0].headers["authorization"].startswith("Basic ")


def test_admin_wins_when_a_person_holds_both_roles(gateway, provider):
    provider.roles = ["readonly", "admin"]
    sign_in(gateway, provider)
    signed_in_as(gateway, "admin")


def test_cookies_are_private_and_lifetime_follows_the_setting(make_gateway, provider):
    with TestClient(
        make_gateway(session_minutes=30), base_url="http://localhost", follow_redirects=False
    ) as browser:
        state = browser.get("/admin/auth/login").headers["set-cookie"].lower()
        assert "httponly" in state and "samesite=lax" in state and "path=/admin/auth" in state
        cookie = sign_in(browser, provider).headers.get_list("set-cookie")
    session = next(item for item in cookie if item.startswith("m87_console_session")).lower()
    assert "httponly" in session and "samesite=strict" in session and "max-age=1800" in session


def test_cookies_are_secure_behind_a_tls_proxy(make_gateway, provider):
    with TestClient(
        make_gateway(public_url="https://gateway.example.test"),
        base_url="http://gateway.example.test",
        follow_redirects=False,
    ) as browser:
        assert "secure" in browser.get("/admin/auth/login").headers["set-cookie"].lower()
        created = browser.post("/admin/api/session", json={"key": KEY})
        assert "secure" in created.headers["set-cookie"].lower()


@pytest.mark.parametrize("roles", [[], ["viewer"], ["ADMIN"]])
def test_no_recognised_role_means_no_access(gateway, provider, roles):
    provider.roles = roles
    assert rejected(sign_in(gateway, provider), "no_role")
    assert gateway.get("/admin/api/session").status_code == 401
    event = gateway.get("/admin/api/management-events", headers=ADMIN).json()["items"][0]
    assert event["action"] == "console.sign_in_denied" and event["actor"] == "alice"


def test_roles_for_another_client_do_not_count(gateway, provider):
    provider.access_overrides = {"resource_access": {"grafana": {"roles": ["admin"]}}}
    assert rejected(sign_in(gateway, provider), "no_role")


def test_roles_can_come_from_the_id_token_with_a_custom_claim(make_gateway, provider):
    provider.id_overrides = {"groups": ["gw-admins"]}
    with TestClient(
        make_gateway(role_claim="groups", admin_role="gw-admins"),
        base_url="http://localhost",
        follow_redirects=False,
    ) as browser:
        sign_in(browser, provider)
        signed_in_as(browser, "admin")


def test_access_token_issued_to_another_client_grants_nothing(gateway, provider):
    provider.access_overrides = {"azp": "another-client"}
    assert rejected(sign_in(gateway, provider), "no_role")


def test_access_token_with_a_bad_signature_grants_nothing(gateway, provider, monkeypatch):
    tokens = provider.tokens

    def forged():
        issued = tokens()
        claims = jwt.decode(issued["access_token"], options={"verify_signature": False})
        issued["access_token"] = signed(claims, OTHER_KEY)
        return issued

    monkeypatch.setattr(provider, "tokens", forged)
    assert rejected(sign_in(gateway, provider), "no_role")


# ---- Forged or misdirected ID tokens


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "another-client"},
        {"iss": "https://evil.example.test/realms/lab"},
        {"exp": 1000},
        {"azp": "another-client"},
        {"nonce": "replayed"},
    ],
)
def test_bad_id_token_claims_are_rejected(gateway, provider, overrides):
    provider.id_overrides = overrides
    assert rejected(sign_in(gateway, provider), "failed")
    assert gateway.get("/admin/api/session").status_code == 401


def test_id_token_signed_by_another_key_is_rejected(gateway, provider):
    provider.id_key = OTHER_KEY
    assert rejected(sign_in(gateway, provider), "failed")


def test_id_token_signed_with_the_client_secret_is_rejected(gateway, provider):
    provider.id_key = SECRET * 3
    provider.id_algorithm = "HS256"
    assert rejected(sign_in(gateway, provider), "failed")


def test_unsigned_id_token_is_rejected(gateway, provider, monkeypatch):
    tokens = provider.tokens

    def unsigned():
        issued = tokens()
        claims = jwt.decode(issued["id_token"], options={"verify_signature": False})
        issued["id_token"] = jwt.encode(
            claims, None, algorithm="none", headers={"kid": "signing-key"}
        )
        return issued

    monkeypatch.setattr(provider, "tokens", unsigned)
    assert rejected(sign_in(gateway, provider), "failed")


# ---- State and login CSRF


def test_callback_needs_the_browser_that_started_sign_in(gateway, provider):
    other = gateway.get("/admin/auth/login")
    state = parse_qs(urlsplit(other.headers["location"]).query)["state"][0]
    gateway.cookies.delete(STATE_COOKIE, path="/admin/auth")
    response = gateway.get(CALLBACK_PATH, params={"code": "x", "state": state})
    assert rejected(response, "expired") and not provider.token_requests


def test_callback_rejects_a_mismatched_state(gateway, provider):
    assert rejected(sign_in(gateway, provider, state="1.forged.state"), "expired")
    assert not provider.token_requests


def test_expired_state_is_rejected(gateway, provider, monkeypatch):
    started = gateway.get("/admin/auth/login")
    state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 601)
    response = gateway.get(CALLBACK_PATH, params={"code": "x", "state": state})
    assert rejected(response, "expired") and not provider.token_requests


def test_provider_error_never_reaches_the_page(gateway):
    started = gateway.get("/admin/auth/login")
    state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
    response = gateway.get(
        CALLBACK_PATH,
        params={"state": state, "error": "access_denied", "error_description": "<script>"},
    )
    assert rejected(response, "failed") and "script" not in response.headers["location"]


# ---- Provider outages and configuration


def test_provider_outage_leaves_the_admin_key_working(gateway, provider):
    provider.down = True
    assert rejected(gateway.get("/admin/auth/login"), "unavailable")
    assert gateway.post("/admin/api/session", json={"key": KEY}).status_code == 204
    signed_in_as(gateway, "admin")


def test_outage_after_a_good_sign_in_is_still_explained(gateway, provider, monkeypatch):
    assert gateway.get("/admin/auth/login").status_code == 302
    provider.down = True
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 16)
    assert rejected(gateway.get("/admin/auth/login"), "unavailable")


def test_discovery_for_another_issuer_is_refused(gateway, provider):
    provider.discovery_issuer = "https://evil.example.test/realms/lab"
    assert rejected(gateway.get("/admin/auth/login"), "unavailable")


def test_without_an_issuer_sso_does_not_exist(make_gateway):
    with TestClient(make_gateway(issuer=""), base_url="http://localhost") as browser:
        assert browser.get("/admin/api/sign-in-options").json() == {"sso": False}
        for path in ("/admin/auth/login", CALLBACK_PATH, "/admin/auth/logout"):
            assert browser.get(path).status_code == 404


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"client_id": ""}, "client ID"),
        ({"public_url": ""}, "public URL"),
        ({"issuer": "http://idp.example.test/realms/lab"}, "HTTPS"),
        ({"public_url": "http://gateway.example.test"}, "HTTPS"),
        ({"issuer": "https://user:pass@idp.example.test"}, "credentials"),
    ],
)
def test_bad_configuration_stops_startup(make_gateway, overrides, message):
    with pytest.raises(RuntimeError, match=message):
        with TestClient(make_gateway(**overrides)):
            pass


def test_missing_secret_stops_startup_without_printing_it(make_gateway, monkeypatch):
    monkeypatch.delenv("GATEWAY_OIDC_CLIENT_SECRET")
    with pytest.raises(RuntimeError, match="client secret"):
        with TestClient(make_gateway()):
            pass


def test_secret_can_come_from_a_file(tmp_path, monkeypatch):
    path = tmp_path / "oidc-secret"
    path.write_text("from-a-file\n")
    monkeypatch.setenv("GATEWAY_OIDC_CLIENT_SECRET_FILE", str(path))
    config = OidcConfig(issuer=ISSUER, client_id=CLIENT_ID, public_url=PUBLIC_URL)
    assert OidcClient.create(config, KEY).client_secret == "from-a-file"
    assert "from-a-file" not in repr(OidcClient.create(config, KEY))


def test_access_log_hides_the_authorization_code():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", f"{CALLBACK_PATH}?code=secret-code&state=s", "1.1", 302), None,
    )  # fmt: skip
    HideSignInCode().filter(record)
    assert "secret-code" not in record.getMessage()


def test_settings_output_never_holds_the_secret(gateway, provider):
    sign_in(gateway, provider)
    for path in ("/admin/api/setup", "/admin/api/features", "/admin/api/diagnostics"):
        assert SECRET not in gateway.get(path).text


# ---- Sessions


def test_signing_out_ends_the_session_and_offers_provider_logout(gateway, provider):
    sign_in(gateway, provider)
    assert gateway.delete("/admin/api/session").status_code == 204
    assert gateway.get("/admin/api/session").status_code == 401
    location = gateway.get("/admin/auth/logout").headers["location"]
    assert location.startswith(f"{ISSUER}/logout?")
    assert parse_qs(urlsplit(location).query)["post_logout_redirect_uri"] == [f"{PUBLIC_URL}/admin"]
    assert "console.signed_out" in {
        item["action"]
        for item in gateway.get("/admin/api/management-events", headers=ADMIN).json()["items"]
    }


def test_session_rejects_tampering_expiry_and_a_changed_admin_key():
    token = issue_session(KEY, ADMIN_KEY_PRINCIPAL)
    assert read_session(token, KEY) == ADMIN_KEY_PRINCIPAL
    body, signature = token.split(".")
    assert read_session(f"{body}x.{signature}", KEY) is None
    assert read_session(token, "a-different-admin-key") is None
    assert read_session(issue_session(KEY, ADMIN_KEY_PRINCIPAL, seconds=-1), KEY) is None
    for junk in ("", "x", "x.y", "1700000000.abc", "." * 3000):
        assert read_session(junk, KEY) is None


def test_old_format_sessions_are_not_accepted():
    import hashlib
    import hmac

    issued = str(int(time.time()))
    signature = hmac.new(KEY.encode(), f"console-session:{issued}".encode(), hashlib.sha256)
    assert read_session(f"{issued}.{signature.hexdigest()}", KEY) is None


def test_session_writes_still_need_the_console_header(gateway, provider):
    sign_in(gateway, provider)
    body = {"project_id": "from-sso", "name": "From SSO"}
    assert gateway.post("/admin/api/projects", json=body).status_code == 401
    assert gateway.post("/admin/api/projects", json=body, headers=CONSOLE).status_code == 201


# ---- Read-only: every route, so a new one cannot slip through

READABLE = {
    ("GET", "/admin/api/about"),
    ("GET", "/admin/api/session"),
    ("GET", "/admin/api/controls"),
    ("GET", "/admin/api/diagnostics"),
    ("GET", "/admin/api/overview"),
    ("GET", "/admin/api/usage"),
    ("GET", "/admin/api/app-names"),
    ("GET", "/admin/api/projects"),
    ("GET", "/admin/api/logs"),
    ("GET", "/admin/api/logs/export"),
    ("GET", "/admin/api/logging-health"),
    ("GET", "/admin/api/logs/{request_id}"),
    ("GET", "/admin/api/apps"),
    ("GET", "/admin/api/apps/{app_id}/keys"),
    ("GET", "/admin/api/management-events"),
    ("GET", "/admin/api/provider-keys"),
    ("GET", "/admin/api/setup"),
    ("GET", "/admin/api/connections/{provider}/models"),
    ("GET", "/admin/api/destinations"),
    ("GET", "/admin/api/configuration/revisions"),
    ("GET", "/admin/api/configuration/revisions/{revision_id}"),
    ("GET", "/admin/api/storage"),
    ("GET", "/admin/api/log-export"),
    ("GET", "/admin/api/features"),
}
PUBLIC = {
    ("GET", "/admin/api/sign-in-options"),
    ("POST", "/admin/api/session"),
    ("DELETE", "/admin/api/session"),
}


def admin_routes(gateway):
    for route in gateway.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/admin/api"):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                yield method, path


def fill(path: str) -> str:
    return (
        path.replace("{provider}", "ollama")
        .replace("{alias}", "default")
        .replace("{revision_id}", "1")
        .replace("{feature_id}", "cache")
        .replace("{request_id}", "missing")
        .replace("{app_id}", "missing")
        .replace("{key_id}", "missing")
        .replace("{project_id}", "missing")
    )


def test_read_only_is_refused_on_every_route_not_on_the_list(gateway, provider):
    provider.roles = ["readonly"]
    sign_in(gateway, provider)
    routes = set(admin_routes(gateway))
    assert READABLE <= routes and PUBLIC <= routes
    refused = routes - READABLE - PUBLIC
    assert len(refused) >= 20
    for method, path in sorted(refused):
        response = gateway.request(method, fill(path), json={}, headers=CONSOLE)
        assert response.status_code == 403, (method, path, response.status_code)
        assert response.json()["error"]["code"] == "insufficient_role"


def test_read_only_can_open_what_is_on_the_list(gateway, provider):
    provider.roles = ["readonly"]
    sign_in(gateway, provider)
    for method, path in sorted(READABLE):
        response = gateway.request(method, fill(path), headers=CONSOLE)
        assert response.status_code != 403, (method, path)


def test_every_route_needs_a_session_except_the_public_ones(gateway):
    for method, path in sorted(set(admin_routes(gateway)) - PUBLIC):
        response = gateway.request(method, fill(path), json={}, headers=CONSOLE)
        assert response.status_code == 401, (method, path, response.status_code)


def test_admin_passes_every_role_check(gateway, provider):
    sign_in(gateway, provider)
    for method, path in sorted(set(admin_routes(gateway)) - PUBLIC):
        if path == "/admin/api/session" or path.endswith("/shutdown"):
            continue
        response = gateway.request(method, fill(path), json={}, headers=CONSOLE)
        assert response.status_code != 403, (method, path)


def test_read_only_sees_metadata_but_not_captured_content(make_gateway, provider):
    prompt = "my private prompt text"
    with TestClient(
        make_gateway(capture=True), base_url="http://localhost", follow_redirects=False
    ) as browser:
        created = browser.post(
            "/admin/api/apps",
            json={"app_id": "reader-test", "allowed_models": ["ollama:test"]},
            headers=ADMIN,
        ).json()
        app_key = created["api_key"]
        sent = browser.post(
            "/v1/chat/completions",
            json={"model": "ollama:test", "messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {app_key}"},
        )
        assert sent.status_code == 200
        request_id = browser.get("/admin/api/logs", headers=ADMIN).json()["items"][0]["request_id"]
        assert prompt in browser.get(f"/admin/api/logs/{request_id}", headers=ADMIN).text

        provider.roles = ["readonly"]
        sign_in(browser, provider)
        listed = browser.get("/admin/api/logs")
        assert request_id in listed.text and prompt not in listed.text
        detail = browser.get(f"/admin/api/logs/{request_id}")
        assert detail.json()["request_id"] == request_id
        assert detail.json()["content_hidden"] is True
        assert prompt not in detail.text and "request_content" not in detail.json()
        assert browser.get("/admin/api/logs/export?include_content=true").status_code == 403
        exported = browser.get("/admin/api/logs/export")
        assert exported.status_code == 200 and prompt not in exported.text
        for path in (
            "/admin/api/apps",
            "/admin/api/apps/reader-test/keys",
            "/admin/api/provider-keys",
        ):
            assert app_key not in browser.get(path).text


def test_read_only_never_sees_stored_provider_keys(gateway, provider):
    stored = "sk-stored-provider-key-value"
    assert (
        gateway.put(
            "/admin/api/provider-keys",
            json={"provider": "openai", "key": stored},
            headers=ADMIN,
        ).status_code
        == 204
    )
    provider.roles = ["readonly"]
    sign_in(gateway, provider)
    for method, path in sorted(READABLE):
        assert stored not in gateway.request(method, fill(path)).text, path


def test_a_refused_write_changes_nothing(gateway, provider):
    provider.roles = ["readonly"]
    sign_in(gateway, provider)
    before = gateway.get("/admin/api/projects").json()
    body = {"project_id": "not-allowed", "name": "Not allowed"}
    assert gateway.post("/admin/api/projects", json=body, headers=CONSOLE).status_code == 403
    assert gateway.get("/admin/api/projects").json() == before


# ---- Audit


def test_changes_are_attributed_to_the_person(gateway, provider):
    sign_in(gateway, provider)
    body = {"project_id": "attributed", "name": "Attributed"}
    assert gateway.post("/admin/api/projects", json=body, headers=CONSOLE).status_code == 201
    events = gateway.get("/admin/api/management-events").json()["items"]
    change = next(item for item in events if item["action"] != "console.signed_in")
    assert change["actor"] == "alice" and change["actor_subject"] == "user-1"
    assert "console.signed_in" in {item["action"] for item in events}


def test_admin_key_changes_say_so(gateway):
    body = {"project_id": "by-key", "name": "By key"}
    assert gateway.post("/admin/api/projects", json=body, headers=ADMIN).status_code == 201
    event = gateway.get("/admin/api/management-events", headers=ADMIN).json()["items"][0]
    assert event["actor"] == "admin-key" and event["actor_subject"] is None


def test_clearing_the_cache_is_audited(gateway, provider):
    sign_in(gateway, provider)
    assert gateway.post("/admin/api/cache/clear", headers=CONSOLE).status_code == 204
    event = gateway.get("/admin/api/management-events").json()["items"][0]
    assert event["action"] == "cache.cleared" and event["actor"] == "alice"


def test_actor_does_not_leak_between_requests(gateway, provider):
    sign_in(gateway, provider)
    body = {"project_id": "by-sso", "name": "By SSO"}
    gateway.post("/admin/api/projects", json=body, headers=CONSOLE)
    gateway.cookies.clear()
    body = {"project_id": "by-key-after", "name": "By key"}
    gateway.post("/admin/api/projects", json=body, headers=ADMIN)
    events = gateway.get("/admin/api/management-events", headers=ADMIN).json()["items"]
    actors = {item["project_id"]: item["actor"] for item in events if item["project_id"]}
    assert actors["by-sso"] == "alice" and actors["by-key-after"] == "admin-key"


def test_features_page_reports_sign_on(gateway):
    items = gateway.get("/admin/api/features", headers=ADMIN).json()["items"]
    item = next(entry for entry in items if entry["id"] == "single_sign_on")
    assert item["status"] == "on" and item["toggleable"] is False


def test_compose_empty_values_keep_defaults(monkeypatch):
    from m87_gateway.config.settings import load_settings

    for name in ("GATEWAY_OIDC_ISSUER", "GATEWAY_OIDC_SCOPES", "GATEWAY_OIDC_SESSION_MINUTES"):
        monkeypatch.setenv(name, "")
    oidc = load_settings(None).control_plane.oidc
    assert (
        oidc.issuer == "" and oidc.scopes == "openid profile email" and oidc.session_minutes == 60
    )


def test_the_container_settings_read_the_environment(tmp_path, monkeypatch):
    """Compose starts the gateway through local_settings, not load_settings."""
    monkeypatch.setenv("GATEWAY_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("GATEWAY_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GATEWAY_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setenv("GATEWAY_OIDC_SESSION_MINUTES", "45")
    oidc = local_settings(tmp_path).control_plane.oidc
    assert (oidc.issuer, oidc.client_id, oidc.public_url) == (ISSUER, CLIENT_ID, PUBLIC_URL)
    assert oidc.session_minutes == 45
