from app.api.authorization import resolve_capabilities
from urllib.parse import parse_qs, urlparse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from app.api import auth
from app.api.dependencies import get_db_session
from app.api.main import app
from app.db.models import Base, DiscordCommunity, DiscordRoleCapability


def test_privileged_endpoint_requires_capability(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def db_override():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db_session] = db_override
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild-id")
    monkeypatch.setenv("DISCORD_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:3000")
    monkeypatch.delenv("DISCORD_OAUTH_CALLBACK_URL", raising=False)
    monkeypatch.setattr(auth, "_http_json", lambda url, **kwargs: (
        {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
        if "oauth2/token" in url else
        {"id": "user", "username": "raider"} if url.endswith("/@me") else
        {"roles": ["role-ordinary"]}))
    try:
        with TestClient(app) as client:
            assert client.get("/api/rbac/mappings").status_code == 401
            assert client.put("/api/players/characters/1/link", json={"player_id": 1}).status_code == 401
            login = client.get("/api/auth/discord/login", follow_redirects=False)
            state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
            callback = client.get("/api/auth/discord/callback", params={"state": state, "code": "code"}, follow_redirects=False)
            cookie = callback.cookies[auth.SESSION_COOKIE]
            initial_authz = client.get("/api/auth/session").json()["authorization"]
            assert initial_authz["is_member"] is True
            assert initial_authz["role_ids"] == ["role-ordinary"]
            assert initial_authz["capabilities"] == []
            assert client.get("/api/rbac/mappings", cookies={auth.SESSION_COOKIE: cookie}).status_code == 403
            assert client.put("/api/players/characters/1/link", json={"player_id": 1},
                              cookies={auth.SESSION_COOKIE: cookie}).status_code == 403
            with factory() as db:
                community = db.query(DiscordCommunity).filter_by(discord_guild_id="guild-id").one()
                db.add(DiscordRoleCapability(community_id=community.id, discord_role_id="role-ordinary",
                                             capability="admin.manage_rbac"))
                db.commit()
            refreshed = client.post("/api/auth/session/refresh", cookies={auth.SESSION_COOKIE: cookie},
                                    headers={"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]})
            assert refreshed.status_code == 200
            assert refreshed.json()["authorization"]["capabilities"] == ["admin.manage_rbac"]
            assert client.get("/api/rbac/mappings", cookies={auth.SESSION_COOKIE: cookie}).status_code == 200
            monkeypatch.setattr(auth, "_http_json", lambda url, **kwargs: (
                {"roles": ["role-revoked"]} if "/member" in url else {"id": "user", "username": "raider"}))
            refreshed = client.post("/api/auth/session/refresh", cookies={auth.SESSION_COOKIE: cookie},
                                    headers={"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]})
            assert refreshed.json()["authorization"]["capabilities"] == []
            assert client.get("/api/rbac/mappings", cookies={auth.SESSION_COOKIE: cookie}).status_code == 403
            with factory() as db:
                db.query(DiscordRoleCapability).filter_by(community_id=community.id).delete()
                db.add(DiscordRoleCapability(community_id=community.id, discord_role_id="role-ordinary",
                                             capability="admin.manage_rbac"))
                db.commit()
            monkeypatch.setattr(auth, "_http_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
            failed = client.post("/api/auth/session/refresh", cookies={auth.SESSION_COOKIE: cookie},
                                 headers={"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]})
            assert failed.status_code == 503
            assert client.get("/api/rbac/mappings", cookies={auth.SESSION_COOKIE: cookie}).status_code == 403
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_policy_unions_mapped_roles_and_ignores_unknown_capabilities():
    result = resolve_capabilities(community_id="main", is_member=True,
        member_role_ids=["role-2", "role-1", "role-2", "unmapped"], mappings=[
            ("role-1", "app.view"), ("role-2", "usage.view"),
            ("role-2", "not.a.real.capability"),
        ])
    assert result.role_ids == ("role-1", "role-2", "unmapped")
    assert result.capabilities == ("app.view", "usage.view")
    assert result.can("app.view")
    assert not result.can("admin.manage_rbac")


def test_non_member_and_unmapped_member_resolve_to_no_capabilities():
    assert resolve_capabilities(community_id="main", is_member=False,
        member_role_ids=["role"], mappings=[("role", "admin.manage_rbac")]).capabilities == ()
    assert resolve_capabilities(community_id="main", is_member=True,
        member_role_ids=["unknown"], mappings=[]).capabilities == ()
