"""Persistence models for browser authentication (not legacy Player links)."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class WebIdentity(Base):
    __tablename__ = "web_identities"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_user_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    sessions: Mapped[list["WebSession"]] = relationship(back_populates="identity", cascade="all, delete-orphan")


class WebSession(Base):
    __tablename__ = "web_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    identity_id: Mapped[int] = mapped_column(ForeignKey("web_identities.id", ondelete="CASCADE"), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discord_access_token_ciphertext: Mapped[str | None] = mapped_column(String(4096))
    discord_refresh_token_ciphertext: Mapped[str | None] = mapped_column(String(4096))
    discord_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    community_guild_id: Mapped[str | None] = mapped_column(String(100))
    membership_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    member_role_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    membership_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    identity: Mapped[WebIdentity] = relationship(back_populates="sessions")


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    state_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    return_to: Mapped[str] = mapped_column(String(2048), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index("ix_web_sessions_expires_at", WebSession.expires_at)
Index("ix_oauth_states_expires_at", OAuthState.expires_at)


class DiscordCommunity(Base):
    __tablename__ = "discord_communities"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    discord_guild_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class DiscordRoleCapability(Base):
    __tablename__ = "discord_role_capabilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("discord_communities.id", ondelete="CASCADE"), nullable=False)
    discord_role_id: Mapped[str] = mapped_column(String(100), nullable=False)
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    community: Mapped[DiscordCommunity] = relationship()
    __table_args__ = (UniqueConstraint("community_id", "discord_role_id", "capability",
                                       name="uq_discord_role_capability"),)
