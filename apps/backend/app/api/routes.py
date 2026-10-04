from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.api.schemas import (HealthResponse, OpenRouterModelsResponse, RbacMappingsResponse, PlayersResponse, ManagedPlayer,
                             CharacterLink, ObservedCharactersResponse, ObservedCharacter, CharacterSource,
                             CharacterLinkRequest, CharacterMutationResponse)
from app.api.authorization import require_capability
from app.api.dependencies import get_db_session
from app.pull_coach.coaching.openrouter_catalog import CatalogUnavailable, catalog_service
from app.db.models import (DiscordCommunity, DiscordRoleCapability, Player, Character,
                           CharacterObservation)
from app.players.linkage import LinkageConflict, link_character, unlink_character

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
def _character(character: Character) -> CharacterLink:
    return CharacterLink(id=character.id, name=character.name, class_name=character.class_name,
                         server=character.server, region=character.region)


@router.get("/players", response_model=PlayersResponse, tags=["players"], operation_id="listPlayers",
            dependencies=[Depends(require_capability("players.manage"))])
def list_players(db: Session = Depends(get_db_session)) -> PlayersResponse:
    players = db.scalars(select(Player).where(Player.discord_id.is_not(None)).order_by(Player.name)).all()
    return PlayersResponse(players=[ManagedPlayer(id=p.id, name=p.name, discord_id=p.discord_id,
        characters=[_character(c) for c in sorted(p.characters, key=lambda c: c.name)]) for p in players])


@router.get("/players/observed-characters", response_model=ObservedCharactersResponse, tags=["players"],
            operation_id="listObservedCharacters", dependencies=[Depends(require_capability("players.manage"))])
def list_observed_characters(search: str | None = Query(default=None, max_length=80),
                             db: Session = Depends(get_db_session)) -> ObservedCharactersResponse:
    query = select(Character).where(Character.player_id.is_(None))
    if search:
        query = query.where(or_(Character.name.ilike(f"%{search}%"), Character.server.ilike(f"%{search}%")))
    rows = db.scalars(query.order_by(Character.name, Character.server, Character.region)).all()
    result = []
    for character in rows:
        observations = db.scalars(select(CharacterObservation).where(
            CharacterObservation.character_id == character.id).order_by(CharacterObservation.id)).all()
        same_name_count = len(db.scalars(select(Character).where(Character.name.ilike(character.name))).all())
        result.append(ObservedCharacter(**_character(character).model_dump(), linked_player_id=None,
            ambiguous=same_name_count > 1,
            sources=[CharacterSource(provider=o.snapshot.provider, report_code=o.snapshot.report_code,
                fight_id=o.snapshot.fight_id, snapshot_id=o.snapshot_id, actor_id=o.actor_id) for o in observations]))
    return ObservedCharactersResponse(characters=result)


@router.put("/players/characters/{character_id}/link", response_model=CharacterMutationResponse,
            tags=["players"], operation_id="linkCharacter",
            dependencies=[Depends(require_capability("players.manage"))])
def put_character_link(character_id: int, request: CharacterLinkRequest,
                       db: Session = Depends(get_db_session)) -> CharacterMutationResponse:
    try:
        character = link_character(db, character_id, request.player_id)
        db.commit()
    except LookupError as error:
        db.rollback()
        raise HTTPException(404, str(error)) from error
    except LinkageConflict as error:
        db.rollback()
        raise HTTPException(409, str(error)) from error
    return CharacterMutationResponse(character=_character(character), player_id=character.player_id)


@router.delete("/players/characters/{character_id}/link", response_model=CharacterMutationResponse,
               tags=["players"], operation_id="unlinkCharacter",
               dependencies=[Depends(require_capability("players.manage"))])
def delete_character_link(character_id: int, db: Session = Depends(get_db_session)) -> CharacterMutationResponse:
    try:
        character = unlink_character(db, character_id)
        db.commit()
    except LookupError as error:
        db.rollback()
        raise HTTPException(404, str(error)) from error
    return CharacterMutationResponse(character=_character(character), player_id=None)
