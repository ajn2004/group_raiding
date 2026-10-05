"""Public API response contracts."""

from pydantic import BaseModel, Field
from typing import Literal

Capability = Literal["app.view", "players.manage", "coaching.configure", "usage.view", "admin.manage_rbac"]
AuthorizationStatus = Literal["member", "not_member", "unavailable", "unknown"]


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
    authorization: "AuthorizationResponse | None" = None


class AuthorizationResponse(BaseModel):
    community: str | None = None
    is_member: bool = False
    role_ids: list[str] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    status: AuthorizationStatus = "unavailable"


class LogoutResponse(BaseModel):
    signed_out: bool


class RbacMappingResponse(BaseModel):
    community: str
    guild_id: str
    role_id: str
    capability: Capability


class RbacMappingsResponse(BaseModel):
    mappings: list[RbacMappingResponse]


class OpenRouterPricingResponse(BaseModel):
    input_dollars_per_million_tokens: str | None
    output_dollars_per_million_tokens: str | None
    input_price_per_token: str | None
    output_price_per_token: str | None
    raw_input_price: str | None
    raw_output_price: str | None
    price_unit: str


class OpenRouterModelResponse(BaseModel):
    id: str
    name: str
    context_length: int | None
    pricing: OpenRouterPricingResponse
    supports_response_format: bool | None
    supports_structured_outputs: bool | None


class OpenRouterModelsResponse(BaseModel):
    status: Literal["available", "degraded"]
    models: list[OpenRouterModelResponse]
    error: Literal["catalog_unavailable"] | None = None


class CharacterLink(BaseModel):
    id: int
    name: str
    class_name: str
    server: str | None = None
    region: str | None = None


class ManagedPlayer(BaseModel):
    id: int
    name: str
    discord_id: int
    characters: list[CharacterLink]


class PlayersResponse(BaseModel):
    players: list[ManagedPlayer]


class CharacterSource(BaseModel):
    provider: str
    report_code: str
    fight_id: str
    snapshot_id: int
    actor_id: str | None = None


class ObservedCharacter(CharacterLink):
    class_name: str
    linked_player_id: int | None = None
    ambiguous: bool = False
    sources: list[CharacterSource]


class ObservedCharactersResponse(BaseModel):
    characters: list[ObservedCharacter]


class CharacterLinkRequest(BaseModel):
    player_id: int


class CharacterMutationResponse(BaseModel):
    character: CharacterLink
    player_id: int | None
