"""Capability policy resolution and reusable API authorization dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.api import auth_repository as repository
from app.db.models import DiscordCommunity, DiscordRoleCapability

CAPABILITIES = frozenset({
    "app.view", "players.manage", "coaching.configure", "usage.view", "admin.manage_rbac",
})


@dataclass(frozen=True)
class AuthorizationContext:
    community_id: str | None
    is_member: bool
    role_ids: tuple[str, ...]
    capabilities: tuple[str, ...]
    status: str = "available"

    def can(self, capability: str) -> bool:
        return capability in self.capabilities


def resolve_capabilities(*, community_id: str | None, is_member: bool,
                         member_role_ids: list[str] | tuple[str, ...],
                         mappings: list[tuple[str, str]]) -> AuthorizationContext:
    """Resolve role IDs to a stable, sorted capability set; never infer rank names."""
    roles = tuple(sorted(set(member_role_ids))) if is_member else ()
    grants = {capability for role_id, capability in mappings if role_id in roles}
    grants.intersection_update(CAPABILITIES)
    return AuthorizationContext(community_id, is_member, roles, tuple(sorted(grants)))


def context_for_session(db: Session, web_session, identity) -> AuthorizationContext:
    guild_id = web_session.community_guild_id
    if not guild_id:
        return AuthorizationContext(None, False, (), ())
    community = db.scalar(select(DiscordCommunity).where(DiscordCommunity.discord_guild_id == guild_id,
                                                          DiscordCommunity.enabled.is_(True)))
    if community is None or web_session.membership_status != "member":
        return AuthorizationContext(community.key if community else None, False, (), ())
    mappings = db.execute(select(DiscordRoleCapability.discord_role_id,
                                 DiscordRoleCapability.capability).where(
        DiscordRoleCapability.community_id == community.id)).all()
    return resolve_capabilities(community_id=community.key, is_member=True,
                                member_role_ids=web_session.member_role_ids or [],
                                mappings=[(row[0], row[1]) for row in mappings])


def current_session(request: Request, db: Session = Depends(get_db_session)):
    from app.api.auth import SESSION_COOKIE, _hash
    cookie = request.cookies.get(SESSION_COOKIE)
    row = repository.find_session(db, _hash(cookie), repository.utc_now()) if cookie else None
    if row is None:
        raise HTTPException(401, "Session required")
    web_session, identity = row
    return web_session, identity


def require_capability(capability: str) -> Callable:
    if capability not in CAPABILITIES:
        raise ValueError(f"Unsupported capability: {capability}")

    def dependency(session_pair=Depends(current_session), db: Session = Depends(get_db_session)):
        web_session, identity = session_pair
        context = context_for_session(db, web_session, identity)
        if not context.can(capability):
            raise HTTPException(403, "Insufficient capability")
        return context
    dependency.__name__ = f"require_{capability.replace('.', '_')}"
    return dependency
