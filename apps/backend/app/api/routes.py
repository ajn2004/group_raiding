from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import HealthResponse, OpenRouterModelsResponse, RbacMappingsResponse
from app.api.authorization import require_capability
from app.api.dependencies import get_db_session
from app.db.models import DiscordCommunity, DiscordRoleCapability
from app.pull_coach.coaching.openrouter_catalog import CatalogUnavailable, catalog_service

router = APIRouter(prefix="/api")


@router.get("/healthz", response_model=HealthResponse, tags=["health"], operation_id="getHealth")
def health() -> HealthResponse:
    return HealthResponse(status="ok", api_version="v1")


@router.get("/rbac/mappings", response_model=RbacMappingsResponse, tags=["authorization"], operation_id="listRbacMappings",
            dependencies=[Depends(require_capability("admin.manage_rbac"))])
def list_rbac_mappings(db: Session = Depends(get_db_session)) -> RbacMappingsResponse:
    rows = db.execute(select(DiscordCommunity, DiscordRoleCapability).join(
        DiscordRoleCapability, DiscordRoleCapability.community_id == DiscordCommunity.id).order_by(
            DiscordCommunity.key, DiscordRoleCapability.discord_role_id, DiscordRoleCapability.capability)).all()
    return {"mappings": [{"community": community.key, "guild_id": community.discord_guild_id,
                           "role_id": mapping.discord_role_id, "capability": mapping.capability}
                           for community, mapping in rows]}


@router.get("/coaching/openrouter/models", response_model=OpenRouterModelsResponse, tags=["coaching"], operation_id="listOpenRouterModels",
            dependencies=[Depends(require_capability("coaching.configure"))])
def list_openrouter_models() -> OpenRouterModelsResponse:
    try:
        models = catalog_service().list_models()
    except CatalogUnavailable:
        return OpenRouterModelsResponse(status="degraded", models=[], error="catalog_unavailable")
    return OpenRouterModelsResponse(status="available", models=[{
        "id": model.id, "name": model.name, "context_length": model.context_length,
        "pricing": {
            "input_dollars_per_million_tokens": model.pricing.input_dollars_per_million_tokens,
            "output_dollars_per_million_tokens": model.pricing.output_dollars_per_million_tokens,
            "input_price_per_token": model.pricing.input_price_per_token,
            "output_price_per_token": model.pricing.output_price_per_token,
            "raw_input_price": model.pricing.raw_input_price,
            "raw_output_price": model.pricing.raw_output_price,
            "price_unit": model.pricing.price_unit,
        }, "supports_response_format": model.supports_response_format,
        "supports_structured_outputs": model.supports_structured_outputs,
    } for model in models])
