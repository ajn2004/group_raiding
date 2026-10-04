from datetime import datetime
from contextlib import contextmanager
import importlib
import sys
import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Character, CharacterObservation, Player, WipefestFightSnapshot
from app.players.linkage import (LinkageConflict, link_character, lookup_character_owner,
                                 lookup_discord_characters, observe_snapshot, unlink_character)


def setup_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def snapshot(db, id, roster):
    row = WipefestFightSnapshot(provider="wipefest", report_code="R1", fight_id=str(id), group_id="G1",
        request_url="https://fixture", request_params={}, fetched_at=datetime.now(),
        payload={"raid": {"players": roster}}, fingerprint=f"fingerprint-{id}")
    db.add(row)
    db.flush()
    return row


def test_observation_is_idempotent_preserves_existing_links_and_records_provenance():
    engine = setup_db()
    with Session(engine) as db:
        player = Player(name="Raider", discord_id=123)
        legacy = Character(name="Known", class_name="Mage", player=player)
        db.add_all([player, legacy])
        db.flush()
        fight = snapshot(db, 1, [{"actorId": 8, "name": "Known", "className": "Mage", "server": "Realm", "region": "EU"},
                                {"actorId": 9, "name": "New", "className": "Druid", "server": "Realm", "region": "EU"}])
        first = observe_snapshot(db, fight)
        assert first[0].player_id == player.id
        assert first[1].player_id is None
        observe_snapshot(db, fight)
        assert db.query(Character).filter_by(name="New").count() == 1
        assert db.query(CharacterObservation).count() == 2
        linked = link_character(db, first[1].id, player.id)
        assert linked.player_id == player.id
        assert [c.name for c in lookup_discord_characters(db, 123)] == ["Known", "New"]
        owner, discord_id = lookup_character_owner(db, name="New", server="Realm", region="EU")
        assert owner.id == player.id and discord_id == 123
        unlink_character(db, linked.id)
        assert linked.player_id is None
    engine.dispose()


def test_link_conflict_requires_explicit_unlink_and_same_name_is_ambiguous():
    engine = setup_db()
    with Session(engine) as db:
        one = Player(name="One", discord_id=1)
        two = Player(name="Two", discord_id=2)
        db.add_all([one, two])
        db.flush()
        db.add_all([Character(name="Twin", class_name="Mage", player_id=one.id, server="A", region="EU"),
                    Character(name="Twin", class_name="Mage", player_id=two.id, server="B", region="EU")])
        db.flush()
        assert lookup_character_owner(db, name="Twin") is None
        assert lookup_character_owner(db, name="Twin", server="A", region="EU")[0].id == one.id
        with pytest.raises(LinkageConflict):
            link_character(db, 1, two.id)
    engine.dispose()


def test_name_only_observation_does_not_choose_between_ambiguous_unlinked_characters():
    engine = setup_db()
    with Session(engine) as db:
        db.add_all([Character(name="Twin", class_name="Mage", player_id=None),
                    Character(name="Twin", class_name="Mage", player_id=None)])
        db.flush()
        before = db.query(Character).count()
        existing_ids = {row.id for row in db.query(Character).filter_by(name="Twin").all()}
        fight = snapshot(db, 2, [{"name": "Twin", "className": "Mage"}])

        observed = observe_snapshot(db, fight)

        assert len(observed) == 1
        assert observed[0].id not in existing_ids
        assert db.query(Character).count() == before + 1
        assert db.query(CharacterObservation).filter_by(character_id=observed[0].id).count() == 1
    engine.dispose()


def test_add_alt_links_unique_observed_unlinked_character_without_duplicate(monkeypatch):
    engine = setup_db()
    with Session(engine) as db:
        player = Player(name="Raider", discord_id=123)
        db.add(player)
        db.flush()
        fight = snapshot(db, 3, [{"name": "andrewalt", "className": "Mage"}])
        observed = observe_snapshot(db, fight)[0]
        observed_id = observed.id
        db.commit()

    @contextmanager
    def test_session_scope():
        session = Session(engine)
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    database_stub = types.ModuleType("app.db.database")
    database_stub.session_scope = test_session_scope
    monkeypatch.setitem(sys.modules, "app.db.database", database_stub)
    sys.modules.pop("app.db.controller", None)
    controller_module = importlib.import_module("app.db.controller")
    monkeypatch.delitem(sys.modules, "app.db.controller", raising=False)
    with Session(engine) as db:
        player_id = db.query(Player).filter_by(discord_id=123).one().id
    result = controller_module.DBController().add_alt({"name": "andrewalt", "class": "mage", "player_id": player_id})

    with Session(engine) as db:
        assert result == "Added andrewalt to the database"
        assert db.query(Character).filter_by(name="andrewalt").count() == 1
        character = db.query(Character).filter_by(name="andrewalt").one()
        assert character.id == observed_id
        assert character.player_id == player_id
    engine.dispose()
