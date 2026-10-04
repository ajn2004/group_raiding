from datetime import datetime, timedelta, timezone
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from app.api import auth_repository
from app.db.models import OAuthState, WebIdentity, WebSession
from app.pull_coach.persistence.coaching_profiles import CoachingProfileRepository


pytestmark = pytest.mark.postgres


def test_migrations_create_core_and_auth_schema(postgres_database):
    db = postgres_database
    inspector = inspect(db["engine"])
    tables = set(inspector.get_table_names(schema=db["schema"]))
    assert {"players", "characters", "wipefest_fight_snapshots", "coaching_profiles",
            "coaching_profile_revisions", "coaching_sessions", "web_identities",
            "web_sessions", "oauth_states", "alembic_version"} <= tables

    schema = db["schema"]
    identity_constraints = inspector.get_unique_constraints("web_identities", schema=schema)
    session_constraints = inspector.get_unique_constraints("web_sessions", schema=schema)
    state_constraints = inspector.get_unique_constraints("oauth_states", schema=schema)
    assert any(c["column_names"] == ["discord_user_id"] for c in identity_constraints)
    assert any(c["column_names"] == ["token_digest"] for c in session_constraints)
    assert any(c["column_names"] == ["state_digest"] for c in state_constraints)
    assert {i["name"] for i in inspector.get_indexes("web_sessions", schema=schema)} >= {"ix_web_sessions_expires_at"}
    assert {i["name"] for i in inspector.get_indexes("oauth_states", schema=schema)} >= {"ix_oauth_states_expires_at"}
    assert any(fk["referred_table"] == "web_identities" and fk["options"].get("ondelete") == "CASCADE"
                for fk in inspector.get_foreign_keys("web_sessions", schema=schema))
    bet_fks = inspector.get_foreign_keys("bet", schema=schema)
    assert {fk["referred_table"] for fk in bet_fks} == {"bet_events", "players", "bet_outcomes"}
    assert sum(fk["referred_table"] == "bet_outcomes" for fk in bet_fks) == 1


def test_auth_migration_downgrade_and_reupgrade_isolated_at_boundary(postgres_database):
    # The full graph has a later merge of the DAL-75 and DAL-89 branches. Use
    # a separate owned schema stopped exactly at DAL-89's parent so the tested
    # downgrade removes only DAL-89, not unrelated later revisions.
    db = postgres_database
    boundary_schema = "dal91_auth_boundary_" + uuid.uuid4().hex
    admin = create_engine(db["base_url"])
    isolated = None
    created = False
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{boundary_schema}"'))
        created = True
        boundary_url = db["base_url"].update_query_dict({"options": f"-csearch_path={boundary_schema}"})
        isolated = create_engine(boundary_url)
        config = Config("alembic.ini")
        config.attributes["version_table_schema"] = boundary_schema
        config.set_main_option("sqlalchemy.url", boundary_url.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(config, "dal89webauth01")
        assert {"web_identities", "web_sessions", "oauth_states"} <= set(inspect(isolated).get_table_names())
        command.downgrade(config, "dal72session001")
        assert not ({"web_identities", "web_sessions", "oauth_states"} & set(inspect(isolated).get_table_names()))
        command.upgrade(config, "dal89webauth01")
        assert {"web_identities", "web_sessions", "oauth_states"} <= set(inspect(isolated).get_table_names())
    finally:
        try:
            if isolated is not None:
                isolated.dispose()
        finally:
            try:
                if created:
                    with admin.begin() as conn:
                        conn.execute(text(f'DROP SCHEMA IF EXISTS "{boundary_schema}" CASCADE'))
            finally:
                admin.dispose()


def test_legacy_player_and_character_data_survives_upgrade(postgres_database):
    db = postgres_database
    schema = "dal91_legacy_" + uuid.uuid4().hex
    admin = create_engine(db["base_url"])
    isolated = None
    created = False
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        url = db["base_url"].update_query_dict({"options": f"-csearch_path={schema}"})
        isolated = create_engine(url)
        with isolated.begin() as conn:
            conn.execute(text("""
                CREATE TABLE players (
                    id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL UNIQUE,
                    discord_id BIGINT, piter_death_tokens INTEGER,
                    tokens_spent INTEGER DEFAULT 0, tokens_received INTEGER DEFAULT 0
                )
            """))
            conn.execute(text("""
                CREATE TABLE characters (
                    id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL,
                    class_name VARCHAR(50) NOT NULL, player_id INTEGER NOT NULL REFERENCES players(id),
                    "mainAlt" BOOLEAN DEFAULT FALSE
                )
            """))
            conn.execute(text("INSERT INTO players (id, name) VALUES (901, 'legacy player')"))
            conn.execute(text("INSERT INTO characters (id, name, class_name, player_id) VALUES (902, 'legacy character', 'Mage', 901)"))
        config = Config("alembic.ini")
        config.attributes["version_table_schema"] = schema
        config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(config, "head")
        with isolated.connect() as conn:
            assert conn.execute(text("SELECT name FROM players WHERE id = 901")).scalar_one() == "legacy player"
            assert conn.execute(text("SELECT name FROM characters WHERE id = 902")).scalar_one() == "legacy character"
    finally:
        try:
            if isolated is not None:
                isolated.dispose()
        finally:
            try:
                if created:
                    with admin.begin() as conn:
                        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            finally:
                admin.dispose()


def test_migrations_ignore_public_collisions_and_preserve_public_state(postgres_database):
    """Exercise migrations against colliding public tables in an owned schema."""
    db = postgres_database
    schema = "dal91_public_isolation_" + uuid.uuid4().hex
    admin = create_engine(db["base_url"])
    isolated = None
    public_created = False
    schema_created = False
    try:
        with admin.begin() as conn:
            existing = conn.execute(text("""
                SELECT to_regclass('public.alembic_version'), to_regclass('public.players'),
                       to_regclass('public.web_identities')
            """)).one()
            assert existing == (None, None, None), "isolation regression requires an otherwise disposable database"
            public_created = True
            conn.execute(text("CREATE TABLE public.alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(text("INSERT INTO public.alembic_version VALUES ('public-sentinel')"))
            conn.execute(text("CREATE TABLE public.players (id INTEGER PRIMARY KEY, sentinel TEXT)"))
            conn.execute(text("INSERT INTO public.players VALUES (1, 'keep-player')"))
            conn.execute(text("CREATE TABLE public.web_identities (id INTEGER PRIMARY KEY, sentinel TEXT)"))
            conn.execute(text("INSERT INTO public.web_identities VALUES (1, 'keep-identity')"))
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            schema_created = True
        url = db["base_url"].update_query_dict({"options": f"-csearch_path={schema}"})
        isolated = create_engine(url)
        config = Config("alembic.ini")
        config.attributes["version_table_schema"] = schema
        config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(config, "head")
        with isolated.connect() as conn:
            assert conn.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar_one() == db["head"]
            assert "sentinel" not in {column["name"] for column in inspect(isolated).get_columns("players", schema=schema)}
            assert conn.execute(text(f'SELECT count(*) FROM "{schema}".players')).scalar_one() == 0
            assert conn.execute(text(f'SELECT sentinel FROM public.players WHERE id = 1')).scalar_one() == "keep-player"
            assert conn.execute(text(f'SELECT sentinel FROM public.web_identities WHERE id = 1')).scalar_one() == "keep-identity"
            assert conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == "public-sentinel"
    finally:
        try:
            if isolated is not None:
                isolated.dispose()
        finally:
            try:
                with admin.begin() as conn:
                    if schema_created:
                        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                    if public_created:
                        conn.execute(text("DROP TABLE IF EXISTS public.web_identities"))
                        conn.execute(text("DROP TABLE IF EXISTS public.players"))
                        conn.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
            finally:
                admin.dispose()


def test_auth_identity_session_readback_expiry_and_revocation(postgres_database):
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    with postgres_database["sessions"]() as writer:
        identity = auth_repository.upsert_identity(writer, "dal91-user", "raider", "Raider", None)
        auth_repository.create_session(writer, identity, "a" * 64, "csrf", now + timedelta(hours=1))
        auth_repository.create_state(writer, "b" * 64, "/raid", now + timedelta(minutes=5))
        writer.commit()
        identity_id = identity.id

    with postgres_database["sessions"]() as reader:
        identity = reader.get(WebIdentity, identity_id)
        session, joined_identity = auth_repository.find_session(reader, "a" * 64, now)
        assert identity.discord_user_id == joined_identity.discord_user_id == "dal91-user"
        assert session.created_at.tzinfo is not None
        assert session.created_at.utcoffset() == timedelta(0)
        assert session.expires_at == now + timedelta(hours=1)
        assert auth_repository.find_session(reader, "a" * 64, now + timedelta(hours=1)) is None
        assert auth_repository.consume_state(reader, "b" * 64, now) == "/raid"
        assert auth_repository.consume_state(reader, "b" * 64, now) is None
        assert auth_repository.invalidate_session(reader, "a" * 64, now) is not None
        reader.commit()

    with postgres_database["sessions"]() as reader:
        assert auth_repository.find_session(reader, "a" * 64, now) is None


def test_postgres_upsert_conflict_rollback_and_caller_transaction(postgres_database):
    sessions = postgres_database["sessions"]
    with sessions() as db:
        identity = auth_repository.upsert_identity(db, "dal91-conflict", "old", "Old", None)
        db.commit()
        identity_id = identity.id
        updated = auth_repository.upsert_identity(db, "dal91-conflict", "new", "New", "avatar")
        assert updated is identity
        assert updated.id == identity_id
        assert updated.username == "new"
        assert updated.display_name == "New"
        assert updated.avatar_url == "avatar"
        auth_repository.create_session(db, updated, "c" * 64, "csrf", datetime.now(timezone.utc) + timedelta(hours=1))
        db.commit()
        second_identity = auth_repository.upsert_identity(db, "dal91-second", "second", "Second", None)
        with pytest.raises(IntegrityError):
            auth_repository.create_session(db, second_identity, "c" * 64, "other", datetime.now(timezone.utc) + timedelta(hours=1))
        db.rollback()
        assert db.scalar(select(WebIdentity).where(WebIdentity.discord_user_id == "dal91-second")) is None

        auth_repository.create_state(db, "d" * 64, "/discard", datetime.now(timezone.utc) + timedelta(minutes=1))
        db.flush()
        db.rollback()
    with sessions() as verify:
        assert verify.scalar(select(OAuthState).where(OAuthState.state_digest == "d" * 64)) is None
        assert verify.scalar(select(WebSession).where(WebSession.token_digest == "c" * 64)) is not None
        persisted = verify.scalar(select(WebIdentity).where(WebIdentity.discord_user_id == "dal91-conflict"))
        assert (persisted.username, persisted.display_name, persisted.avatar_url) == ("new", "New", "avatar")


def test_auth_and_coaching_profiles_share_migrated_session(postgres_database):
    with postgres_database["sessions"]() as db:
        identity = auth_repository.upsert_identity(db, "dal91-shared", "shared", "Shared", None)
        revision = CoachingProfileRepository(db).create_revision(
            "dal91_test", provider="test", model_slug="test/model", system_prompt="system",
            user_prompt_template="user", output_schema_version="test-v1", activate=True,
        )
        db.commit()
        identity_id, revision_id = identity.id, revision.id
    with postgres_database["sessions"]() as verify:
        assert verify.get(WebIdentity, identity_id) is not None
        assert CoachingProfileRepository(verify).active("dal91_test").active_revision_id == revision_id
