from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse, parse_qs as parse_form
from email.message import Message
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api import auth
from app.api.main import app


def test_discord_token_exchange_uses_documented_form_request(monkeypatch):
    body = None
    captured = {}
    class Result:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return b'{"access_token":"token"}'
    def open_request(request, timeout):
        nonlocal body
        captured.update(url=request.full_url, headers=dict(request.header_items()), timeout=timeout)
        body = request.data
        return Result()
    with patch.object(auth, "urlopen", open_request):
        assert auth._http_json("https://discord.com/api/oauth2/token", data={
            "client_id": "client-id", "client_secret": "top-secret", "grant_type": "authorization_code",
            "code": "fresh-code", "redirect_uri": "https://example.test/api/auth/discord/callback",
        }) == {"access_token": "token"}
    assert captured["url"] == "https://discord.com/api/oauth2/token"
    assert captured["headers"]["Content-type"] == "application/x-www-form-urlencoded"
    assert captured["headers"]["Accept"] == "application/json"
    assert parse_form(body.decode()) == {
        "client_id": ["client-id"], "client_secret": ["top-secret"], "grant_type": ["authorization_code"],
        "code": ["fresh-code"], "redirect_uri": ["https://example.test/api/auth/discord/callback"],
    }


@pytest.mark.parametrize(("content_type", "body", "kind"), [
    ("application/json", b'{"error":"invalid_grant","error_description":"bad code"}', "json_error"),
    ("text/html", b"<html>secret response body</html>", "html_block_or_intermediary"),
])
def test_http_403_diagnostics_classify_response_without_logging_body(content_type, body, kind, caplog):
    headers = Message()
    headers["Content-Type"] = content_type
    exc = HTTPError("https://discord.com/api/oauth2/token", 403, "Forbidden", headers, BytesIO(body))
    auth._log_callback_failure("token_exchange", exc)
    assert f"response_kind={kind}" in caplog.text
    assert "http_status=403" in caplog.text
    assert "secret response body" not in caplog.text
    if content_type == "application/json":
        assert "oauth_error=invalid_grant" in caplog.text
        assert "oauth_error_description=bad code" in caplog.text


def test_uvicorn_callback_access_log_query_is_redacted():
    from app.api.main import _RedactOAuthCallbackQuery
    import logging

    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("client", "GET", "/api/auth/discord/callback?code=secret&state=secret", "1.1", 302), None)
    _RedactOAuthCallbackQuery().filter(record)
    assert "secret" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_SESSION_DATABASE", str(tmp_path / "sessions.sqlite3"))
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild-id")
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:3000")
    monkeypatch.delenv("DISCORD_OAUTH_CALLBACK_URL", raising=False)
    return TestClient(app)


def test_login_creates_state_and_uses_minimum_identity_scopes(client):
    response = client.get("/api/auth/discord/login?return_to=%2Fraid", follow_redirects=False)
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["scope"] == ["identify guilds.members.read"]
    assert query["redirect_uri"] == ["http://localhost:3000/api/auth/discord/callback"]
    assert len(query["state"][0]) >= 40
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "secure" not in response.headers["set-cookie"].lower()
    invalid = client.get("/api/auth/discord/callback", params={"state": "bad", "code": "x"}, follow_redirects=False)
    assert invalid.status_code == 302
    assert invalid.headers["location"] == "/?auth=error"
    assert f'{auth.OAUTH_STATE_COOKIE}="";' in invalid.headers["set-cookie"]


def test_callback_restores_session_and_logout_invalidates_it(client, monkeypatch):
    monkeypatch.setattr(auth, "_http_json", lambda url, **kwargs: {"access_token": "never-client-side"} if "oauth2/token" in url else {"id": "42", "username": "raider", "global_name": "Raider", "avatar": "hash"})
    login = client.get("/api/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    callback = client.get("/api/auth/discord/callback", params={"state": state, "code": "code"}, follow_redirects=False)
    assert callback.status_code == 302 and callback.headers["location"] == "/"
    cookie = callback.cookies[auth.SESSION_COOKIE]
    assert "httponly" in callback.headers["set-cookie"].lower()
    assert "secure" not in callback.headers["set-cookie"].lower()
    restored = client.get("/api/auth/session")
    assert {key: value for key, value in restored.json().items() if key != "csrf_token"} == {
        "authenticated": True, "discord_user_id": "42", "username": "raider", "display_name": "Raider",
        "avatar_url": "https://cdn.discordapp.com/avatars/42/hash.png",
    }
    assert len(restored.json()["csrf_token"]) >= 40
    assert "never-client-side" not in restored.text
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": restored.json()["csrf_token"]}).json() == {"signed_out": True}
    assert client.get("/api/auth/session", cookies={auth.SESSION_COOKIE: cookie}).json()["authenticated"] is False


def test_state_is_single_use_and_provider_denial_returns_neutral_redirect(client):
    login = client.get("/api/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    assert client.get("/api/auth/discord/callback", params={"state": state, "error": "access_denied"}, follow_redirects=False).headers["location"] == "/?auth=cancelled"
    replay = client.get("/api/auth/discord/callback", params={"state": state, "code": "code"}, follow_redirects=False)
    assert replay.status_code == 302
    assert replay.headers["location"] == "/?auth=error"


def test_expired_oauth_state_redirects_and_clears_state_cookie(client):
    login = client.get("/api/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    with auth._connect() as db:
        db.execute("UPDATE oauth_states SET expires_at=0 WHERE state_hash=?", (auth._hash(state),))

    response = client.get("/api/auth/discord/callback", params={"state": state, "code": "code"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/?auth=error"
    cookie_header = response.headers["set-cookie"].lower()
    assert f'{auth.OAUTH_STATE_COOKIE}="";' in cookie_header
    assert "max-age=0" in cookie_header


def test_production_cookie_is_secure(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://group.example")
    monkeypatch.setattr(auth, "_http_json", lambda url, **kwargs: {"access_token": "fake"} if "oauth2/token" in url else {"id": "42", "username": "raider"})
    secure_client = TestClient(app, base_url="https://group.example")
    login = secure_client.get("/api/auth/discord/login", follow_redirects=False)
    assert "secure" in login.headers["set-cookie"].lower()
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    response = secure_client.get("/api/auth/discord/callback", params={"state": state, "code": "fake"}, follow_redirects=False)
    assert "secure" in response.headers["set-cookie"].lower()
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()


def test_oauth_state_is_bound_to_the_initiating_browser(client):
    login = client.get("/api/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    mismatched = client.get("/api/auth/discord/callback", params={"state": state, "code": "code"}, cookies={auth.OAUTH_STATE_COOKIE: "other-browser-state"}, follow_redirects=False)
    assert mismatched.status_code == 302
    assert mismatched.headers["location"] == "/?auth=error"


def test_provider_failure_does_not_create_session(client, monkeypatch):
    monkeypatch.setattr(auth, "_http_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("provider down")))
    login = client.get("/api/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    callback = client.get("/api/auth/discord/callback", params={"state": state, "code": "fake"}, follow_redirects=False)
    assert callback.headers["location"] == "/?auth=error"
    assert auth.SESSION_COOKIE not in callback.headers.get("set-cookie", "")


@pytest.mark.parametrize(("failure_stage", "expected_stage"), [
    ("token", "token_exchange"), ("user", "user_lookup"),
])
def test_callback_logs_provider_failure_stage_without_sensitive_details(client, monkeypatch, caplog, failure_stage, expected_stage):
    def provider(url, **kwargs):
        if failure_stage == "token" or "users/@me" in url:
            raise OSError("request contained access_token=super-secret")
        return {"access_token": "super-secret"}

    monkeypatch.setattr(auth, "_http_json", provider)
    login = client.get("/api/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    response = client.get("/api/auth/discord/callback", params={"state": state, "code": "secret-code"}, follow_redirects=False)
    assert response.headers["location"] == "/?auth=error"
    assert f"stage={expected_stage}" in caplog.text
    assert "OSError" in caplog.text
    assert "super-secret" not in caplog.text
    assert "secret-code" not in caplog.text


def test_callback_logs_session_persistence_failure(client, monkeypatch, caplog):
    monkeypatch.setattr(auth, "_http_json", lambda url, **kwargs: {"access_token": "token"} if "oauth2/token" in url else {"id": "42", "username": "raider"})
    connect = auth._connect
    calls = 0
    def fail_session_write():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("disk unavailable")
        return connect()
    monkeypatch.setattr(auth, "_connect", fail_session_write)
    login = client.get("/api/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    response = client.get("/api/auth/discord/callback", params={"state": state, "code": "secret-code"}, follow_redirects=False)
    assert response.headers["location"] == "/?auth=error"
    assert "stage=session_persistence" in caplog.text
    assert "secret-code" not in caplog.text


def test_expired_session_is_rejected(client, monkeypatch):
    monkeypatch.setattr(auth, "_http_json", lambda url, **kwargs: {"access_token": "fake"} if "oauth2/token" in url else {"id": "42", "username": "raider"})
    login = client.get("/api/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    callback = client.get("/api/auth/discord/callback", params={"state": state, "code": "fake"}, follow_redirects=False)
    cookie = callback.cookies[auth.SESSION_COOKIE]
    with auth._connect() as db:
        db.execute("UPDATE web_sessions SET expires_at=0")
    assert client.get("/api/auth/session", cookies={auth.SESSION_COOKIE: cookie}).json()["authenticated"] is False
