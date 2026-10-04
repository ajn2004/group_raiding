"""Public API response contracts."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    api_version: str


class AuthSessionResponse(BaseModel):
    authenticated: bool
    discord_user_id: str | None = None
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    csrf_token: str | None = None


class LogoutResponse(BaseModel):
    signed_out: bool
