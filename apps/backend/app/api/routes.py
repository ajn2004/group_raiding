from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import HealthResponse, RbacMappingsResponse
from app.api.authorization import require_capability
from app.api.dependencies import get_db_session
from app.db.models import DiscordCommunity, DiscordRoleCapability

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
