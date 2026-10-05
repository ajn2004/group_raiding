"""Ingest-aware player/character identity operations, independent of HTTP and Discord."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Character, CharacterObservation, Player, WipefestFightSnapshot


class LinkageConflict(ValueError):
    pass


def _identity(name: str, server: str | None, region: str | None):
    return name.strip().casefold(), (server or "").strip().casefold(), (region or "").strip().casefold()


def _roster(payload: dict):
    raid = payload.get("raid") or {}
    players = raid.get("players", []) if isinstance(raid, dict) else []
    for row in players if isinstance(players, list) else []:
        if isinstance(row, dict) and isinstance(row.get("name"), str) and row["name"].strip():
            yield row


def observe_snapshot(db: Session, snapshot: WipefestFightSnapshot) -> list[Character]:
    """Idempotently record roster identities and source provenance without inventing owners."""
    observed = []
    for row in _roster(snapshot.payload):
        name, server, region = row["name"].strip(), row.get("server"), row.get("region")
        key = _identity(name, server, region)
        matches = list(db.scalars(select(Character).where(Character.name.ilike(name))))
        exact = [c for c in matches if _identity(c.name, c.server, c.region) == key]
        # A unique legacy name-only row can be enriched in place, preserving its
        # explicit owner. Multiple same-name rows are deliberately ambiguous.
        if not exact and len(matches) == 1 and not matches[0].server and not matches[0].region:
            exact = matches
        if not server and not region:
            if len(matches) > 1:
                ambiguous_candidates = [c for c in matches if c.player_id is None and not c.server and not c.region]
                exact = ambiguous_candidates if len(ambiguous_candidates) == 1 else []
            else:
                exact = matches
        character = exact[0] if exact else None
        if character is not None:
            character.server = character.server or server
            character.region = character.region or region
        if character is None:
            character = Character(name=name, class_name=str(row.get("className") or "Unknown"),
                                  player_id=None, server=server, region=region)
            db.add(character)
            db.flush()
        provenance = db.scalar(select(CharacterObservation).where(
            CharacterObservation.character_id == character.id,
            CharacterObservation.snapshot_id == snapshot.id))
        if provenance is None:
            db.add(CharacterObservation(character_id=character.id, snapshot_id=snapshot.id,
                                        actor_id=str(row.get("actorId", row.get("id")))
                                        if row.get("actorId", row.get("id")) is not None else None))
        observed.append(character)
    db.flush()
    return observed


def link_character(db: Session, character_id: int, player_id: int) -> Character:
    character = db.get(Character, character_id)
    player = db.get(Player, player_id)
    if character is None or player is None:
        raise LookupError("Character or Player not found")
    if character.player_id is not None and character.player_id != player.id:
        raise LinkageConflict("Character is linked to another Player; unlink it explicitly first")
    character.player_id = player.id
    db.flush()
    return character


def unlink_character(db: Session, character_id: int) -> Character:
    character = db.get(Character, character_id)
    if character is None:
        raise LookupError("Character not found")
    character.player_id = None
    db.flush()
    return character


def lookup_discord_characters(db: Session, discord_id: int) -> list[Character]:
    return list(db.scalars(select(Character).join(Player).where(Player.discord_id == discord_id).order_by(Character.name)))


def lookup_character_owner(db: Session, *, name: str, server: str | None = None,
                           region: str | None = None) -> tuple[Player, int | None] | None:
    rows = list(db.scalars(select(Character).where(Character.name.ilike(name))))
    key = _identity(name, server, region)
    matched = [c for c in rows if _identity(c.name, c.server, c.region) == key]
    if not server and not region:
        matched = rows if len(rows) == 1 else []
    if len(matched) != 1 or matched[0].player_id is None:
        return None
    owner = db.get(Player, matched[0].player_id)
    return (owner, owner.discord_id) if owner else None
