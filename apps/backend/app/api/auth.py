"""Discord OAuth and opaque, server-side web sessions."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

from app.api.schemas import AuthSessionResponse, LogoutResponse
from app.api.dependencies import get_db_session
from app.api import auth_repository as repository
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet, InvalidToken
from app.api.authorization import context_for_session

router = APIRouter(prefix="/auth", tags=["authentication"])
load_dotenv()
SESSION_COOKIE = "group_raiding_session"
OAUTH_STATE_COOKIE = "group_raiding_oauth_state"
SESSION_TTL = 60 * 60 * 24 * 14
STATE_TTL = 600
logger = logging.getLogger(__name__)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


def _settings() -> tuple[str, str, str, str, bool]:
    client_id = os.getenv("DISCORD_OAUTH_CLIENT_ID", "")
    client_secret = os.getenv("DISCORD_OAUTH_CLIENT_SECRET", "")
    app_url = os.getenv("PUBLIC_APP_URL", "http://localhost:3000").rstrip("/")
    callback = os.getenv("DISCORD_OAUTH_CALLBACK_URL", f"{app_url}/api/auth/discord/callback")
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    if not client_id or not client_secret or not guild_id:
        raise HTTPException(503, "Discord sign-in is not configured")
    if callback != f"{app_url}/api/auth/discord/callback":
        raise HTTPException(503, "Discord callback must use the public application origin")
    return client_id, client_secret, callback, guild_id, app_url.startswith("https://")


def _http_json(url: str, *, data: dict | None = None, token: str | None = None) -> dict:
    payload = urlencode(data).encode() if data is not None else None
    headers = {"Accept": "application/json", "User-Agent": "GroupRaiding/1.0 (+Discord OAuth)"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = URLRequest(url, data=payload, headers=headers)
    with urlopen(request, timeout=10) as result:
        return json.loads(result.read())


def _fernet() -> Fernet:
    key = os.getenv("DISCORD_TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise HTTPException(503, "Discord token encryption is not configured")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, "Discord token encryption configuration is invalid") from exc


def _encrypt_token(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt_token(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, UnicodeDecodeError):
        return None


def _refresh_membership(db: Session, web_session, *, access_token: str | None = None) -> bool:
    """Refresh current member roles; a provider failure clears all cached grants."""
    now = repository.utc_now()
    try:
        token_expires_at = web_session.discord_token_expires_at
        if token_expires_at is not None and token_expires_at.tzinfo is None:
            token_expires_at = token_expires_at.replace(tzinfo=timezone.utc)
        if access_token is None and token_expires_at and token_expires_at <= now:
            refresh_token = _decrypt_token(web_session.discord_refresh_token_ciphertext)
            if not refresh_token:
                raise RuntimeError("Discord refresh credential unavailable")
            client_id, client_secret, _, _, _ = _settings()
            payload = _http_json("https://discord.com/api/oauth2/token", data={
                "client_id": client_id, "client_secret": client_secret,
                "grant_type": "refresh_token", "refresh_token": refresh_token,
            })
            access_token = payload["access_token"]
            web_session.discord_refresh_token_ciphertext = _encrypt_token(payload.get("refresh_token", refresh_token))
            web_session.discord_access_token_ciphertext = _encrypt_token(access_token)
            web_session.discord_token_expires_at = now + timedelta(seconds=int(payload.get("expires_in", 3600)))
        token = access_token or _decrypt_token(web_session.discord_access_token_ciphertext)
        if not token:
            raise RuntimeError("Discord access credential unavailable")
        payload = _http_json(f"https://discord.com/api/users/@me/guilds/{web_session.community_guild_id}/member", token=token)
        roles = payload.get("roles")
        if not isinstance(roles, list) or not all(isinstance(role, (str, int)) for role in roles):
            raise ValueError("Malformed Discord guild member response")
        web_session.membership_status = "member"
        web_session.member_role_ids = sorted({str(role) for role in roles})
        web_session.membership_refreshed_at = now
        return True
    except (OSError, TimeoutError, ValueError, KeyError, RuntimeError, TypeError, HTTPException) as exc:
        # Network/client errors and malformed provider payloads fail closed;
        # callback diagnostics omit raw response bodies and credentials.
        _log_callback_failure("guild_membership_refresh", exc)
        from urllib.error import HTTPError
        if isinstance(exc, HTTPError) and exc.code == 404:
            web_session.membership_status = "not_member"
            web_session.member_role_ids = []
            web_session.membership_refreshed_at = now
            return True
        web_session.membership_status = "unavailable"
        web_session.member_role_ids = []
        web_session.membership_refreshed_at = now
        return False


def _auth_context(db: Session, web_session, identity) -> dict:
    context = context_for_session(db, web_session, identity)
    return {"community": context.community_id, "is_member": context.is_member,
            "role_ids": list(context.role_ids), "capabilities": list(context.capabilities),
            "status": web_session.membership_status}


def _log_callback_failure(stage: str, exc: Exception) -> None:
    """Log diagnostic metadata only; exception messages/bodies may contain secrets."""
    from urllib.error import HTTPError

    status = exc.code if isinstance(exc, HTTPError) else None
    content_type = "unknown"
    response_kind = "not_http_error"
    oauth_error = oauth_description = None
    proxy_configured = any(os.getenv(name) for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"))
    if isinstance(exc, HTTPError):
        content_type = (exc.headers.get_content_type() if exc.headers else "unknown")
        try:
            body = exc.read(16384)
        except OSError:
            body = b""
        if "json" in content_type:
            response_kind = "json_error"
            try:
                payload = json.loads(body)
                if isinstance(payload, dict):
                    oauth_error = _safe_provider_field(payload.get("error"))
                    oauth_description = _safe_provider_field(payload.get("error_description"))
            except (ValueError, UnicodeDecodeError):
                response_kind = "invalid_json"
        elif content_type == "text/html":
            response_kind = "html_block_or_intermediary"
        else:
            response_kind = "non_json_response"
    config_complete = all(os.getenv(name) for name in ("DISCORD_OAUTH_CLIENT_ID", "DISCORD_OAUTH_CLIENT_SECRET", "DISCORD_GUILD_ID"))
    app_url = os.getenv("PUBLIC_APP_URL", "http://localhost:3000").rstrip("/")
    configured_callback = os.getenv("DISCORD_OAUTH_CALLBACK_URL", f"{app_url}/api/auth/discord/callback")
    callback_consistent = configured_callback == f"{app_url}/api/auth/discord/callback"
    logger.error(
        "Discord OAuth callback failed stage=%s error_type=%s http_status=%s content_type=%s response_kind=%s oauth_error=%s oauth_error_description=%s proxy_env_configured=%s oauth_config_complete=%s redirect_uri_consistent=%s",
        stage, type(exc).__name__, status, content_type, response_kind,
        oauth_error, oauth_description, proxy_configured, config_complete, callback_consistent,
    )


def _safe_provider_field(value: object) -> str | None:
    """Keep allowlisted provider error fields bounded and scrub common secret forms."""
    import re

    if not isinstance(value, str):
        return None
    value = re.sub(r"(?i)(access_token|refresh_token|client_secret|client_id|code|state|authorization)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", value)
    value = re.sub(r"(?i)Bearer\s+\S+", "Bearer [REDACTED]", value)
    return value[:200]


def _set_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, httponly=True,
                        secure=secure, samesite="lax", path="/")


@router.get("/session", response_model=AuthSessionResponse, operation_id="getAuthSession")
def session(session_cookie: str | None = Cookie(None, alias=SESSION_COOKIE), db: Session = Depends(get_db_session)) -> AuthSessionResponse:
    if not session_cookie:
        return AuthSessionResponse(authenticated=False)
    row = repository.find_session(db, _hash(session_cookie), repository.utc_now())
    if not row:
        return AuthSessionResponse(authenticated=False)
    stored, identity = row
    return AuthSessionResponse(authenticated=True, discord_user_id=identity.discord_user_id,
                               username=identity.username, display_name=identity.display_name,
                               avatar_url=identity.avatar_url, csrf_token=stored.csrf_token,
                               authorization=_auth_context(db, stored, identity))


@router.post("/session/refresh", response_model=AuthSessionResponse, operation_id="refreshAuthSession")
def refresh_session(session_cookie: str | None = Cookie(None, alias=SESSION_COOKIE),
                    x_csrf_token: str | None = Header(None),
                    db: Session = Depends(get_db_session)) -> AuthSessionResponse:
    if not session_cookie:
        raise HTTPException(401, "Session required")
    row = repository.find_session(db, _hash(session_cookie), repository.utc_now())
    if not row:
        raise HTTPException(401, "Session expired")
    stored, identity = row
    if not x_csrf_token or not secrets.compare_digest(stored.csrf_token, x_csrf_token):
        raise HTTPException(403, "Invalid CSRF token")
    if not _refresh_membership(db, stored):
        db.commit()
        raise HTTPException(503, "Discord membership is temporarily unavailable")
    db.commit()
    return AuthSessionResponse(authenticated=True, discord_user_id=identity.discord_user_id,
        username=identity.username, display_name=identity.display_name, avatar_url=identity.avatar_url,
        csrf_token=stored.csrf_token, authorization=_auth_context(db, stored, identity))


@router.get("/discord/login", status_code=302, operation_id="loginWithDiscord")
def discord_login(return_to: str | None = Query(None), db: Session = Depends(get_db_session)) -> RedirectResponse:
    client_id, _, callback, _, secure = _settings()
    state = secrets.token_urlsafe(32)
    try:
        db.query(repository.OAuthState).filter(repository.OAuthState.expires_at <= repository.utc_now()).delete()
        repository.create_state(db, _hash(state), _safe_return_to(return_to), repository.utc_now() + timedelta(seconds=STATE_TTL))
        db.commit()
    except Exception:
        db.rollback()
        raise
    params = urlencode({"client_id": client_id, "redirect_uri": callback, "response_type": "code",
                        "scope": "identify guilds.members.read", "state": state})
    response = RedirectResponse(f"https://discord.com/oauth2/authorize?{params}", status_code=302)
    response.set_cookie(OAUTH_STATE_COOKIE, state, max_age=STATE_TTL, httponly=True,
                        secure=secure, samesite="lax", path="/")
    return response


@router.get("/discord/callback", status_code=302, operation_id="discordCallback", include_in_schema=True)
def discord_callback(code: str | None = None, state: str | None = None,
                     state_cookie: str | None = Cookie(None, alias=OAUTH_STATE_COOKIE),
                     error: str | None = None, db: Session = Depends(get_db_session)) -> Response:
    client_id, client_secret, callback, guild_id, secure = _settings()

    def invalid_state_redirect() -> RedirectResponse:
        redirect = RedirectResponse("/?auth=error", status_code=302)
        redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
        return redirect

    if not state or not state_cookie or not secrets.compare_digest(state, state_cookie):
        return invalid_state_redirect()
    try:
        return_to = repository.consume_state(db, _hash(state), repository.utc_now())
        db.commit()  # consumed before provider requests; failed exchanges cannot replay state
    except Exception:
        db.rollback()
        return invalid_state_redirect()
    if not return_to:
        return invalid_state_redirect()
    if error:
        redirect = RedirectResponse("/?auth=cancelled", status_code=302)
        redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
        return redirect
    if not code:
        return invalid_state_redirect()
    try:
        token_payload = _http_json("https://discord.com/api/oauth2/token", data={
            "client_id": client_id, "client_secret": client_secret, "grant_type": "authorization_code",
            "code": code, "redirect_uri": callback,
        })
        access_token = token_payload["access_token"]
    except Exception as exc:
        _log_callback_failure("token_exchange", exc)
        redirect = RedirectResponse("/?auth=error", status_code=302)
        redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
        return redirect
    try:
        user = _http_json("https://discord.com/api/users/@me", token=access_token)
    except Exception as exc:
        _log_callback_failure("user_lookup", exc)
        redirect = RedirectResponse("/?auth=error", status_code=302)
        redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
        return redirect
    # Resolve membership when available, but never turn it into an authz decision.
    try:
        member_payload = _http_json(f"https://discord.com/api/users/@me/guilds/{guild_id}/member", token=access_token)
    except Exception as exc:
        from urllib.error import HTTPError
        member_payload = {"_not_member": True} if isinstance(exc, HTTPError) and exc.code == 404 else None
        if member_payload is None:
            _log_callback_failure("guild_membership_lookup", exc)
    avatar = user.get("avatar")
    identity = {"discord_user_id": str(user["id"]), "username": user.get("username", ""),
                "display_name": user.get("global_name") or user.get("username", ""),
                "avatar_url": f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png" if avatar else None}
    raw_session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    try:
        web_identity = repository.upsert_identity(db, identity["discord_user_id"], identity["username"],
                                                  identity["display_name"], identity["avatar_url"])
        repository.ensure_community(db, guild_id)
        expiry = repository.utc_now() + timedelta(seconds=SESSION_TTL)
        web_session = repository.create_session(db, web_identity, _hash(raw_session), csrf, expiry,
            discord_access_token_ciphertext=_encrypt_token(access_token),
            discord_refresh_token_ciphertext=_encrypt_token(token_payload["refresh_token"]) if token_payload.get("refresh_token") else None,
            discord_token_expires_at=repository.utc_now() + timedelta(seconds=int(token_payload.get("expires_in", 3600))),
            community_guild_id=guild_id,
            membership_status="not_member" if isinstance(member_payload, dict) and member_payload.get("_not_member") else
                "member" if isinstance(member_payload, dict) and isinstance(member_payload.get("roles"), list)
                and all(isinstance(role, (int, str)) for role in member_payload.get("roles", [])) else "unavailable",
            member_role_ids=sorted({str(role) for role in member_payload.get("roles", [])})
                if isinstance(member_payload, dict) and isinstance(member_payload.get("roles"), list)
                and all(isinstance(role, (int, str)) for role in member_payload.get("roles", [])) else [])
        db.commit()
    except Exception as exc:
        db.rollback()
        _log_callback_failure("session_persistence", exc)
        redirect = RedirectResponse("/?auth=error", status_code=302)
        redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
        return redirect
    redirect = RedirectResponse(_safe_return_to(return_to), status_code=302)
    redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    _set_cookie(redirect, raw_session, secure)
    return redirect


@router.post("/logout", response_model=LogoutResponse, operation_id="logout")
def logout(response: Response, session_cookie: str | None = Cookie(None, alias=SESSION_COOKIE),
           x_csrf_token: str | None = Header(None), db: Session = Depends(get_db_session)) -> LogoutResponse:
    _, _, _, _, secure = _settings()
    if not session_cookie:
        raise HTTPException(401, "Session required")
    token_hash = _hash(session_cookie)
    row = repository.find_session(db, token_hash, repository.utc_now())
    if not row:
        raise HTTPException(401, "Session expired")
    if not x_csrf_token or not secrets.compare_digest(row[0].csrf_token, x_csrf_token):
        raise HTTPException(403, "Invalid CSRF token")
    try:
        repository.invalidate_session(db, token_hash, repository.utc_now())
        db.commit()
    except Exception:
        db.rollback()
        raise
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    return LogoutResponse(signed_out=True)
