"""Opt-in acceptance test for a genuinely empty PostgreSQL database.

Set TEST_POSTGRES_ADMIN_URL to a PostgreSQL URL whose user can create/drop
databases. The test creates a uniquely named database and always drops it.
"""

import os
import subprocess
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_ADMIN_URL"), reason="PostgreSQL admin URL not configured")
def test_empty_postgres_database_upgrades_to_single_head():
    admin_url = make_url(os.environ["TEST_POSTGRES_ADMIN_URL"])
    database_name = f"dal92_bootstrap_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target_url = admin_url.set(database=database_name)
    env = os.environ.copy()
    env.update({
        "SQLALCHEMY_DATABASE_USER": admin_url.username or "",
        "SQLALCHEMY_DATABASE_PASSWORD": admin_url.password or "",
        "SQLALCHEMY_DATABASE_HOST": admin_url.host or "localhost",
        "SQLALCHEMY_DATABASE_PORT": str(admin_url.port or 5432),
        "SQLALCHEMY_DATABASE_DB": database_name,
    })

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        def run(*args):
            return subprocess.run(
                ["uv", "run", "alembic", *args], cwd=os.path.dirname(__file__) + "/..",
                env=env, check=True, capture_output=True, text=True,
            )

        run("upgrade", "head")
        current = run("current").stdout
        assert "dal92merge01 (head)" in current
        with create_engine(target_url).connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            assert {
                "players", "characters", "schedule", "roles", "specializations", "buffs", "usage",
                "bet", "bet_events", "bet_outcomes", "pull_coach_reports", "wipefest_fight_snapshots",
                "coaching_profiles", "coaching_profile_revisions", "coaching_sessions",
                "coaching_session_messages", "web_identities", "web_sessions", "oauth_states",
            } <= tables
            session_columns = {column["name"] for column in inspector.get_columns("coaching_sessions")}
            assert {"candidate_insights", "insight_gate_decisions", "displayed_insight_ids", "insight_provenance"} <= session_columns

        second = run("upgrade", "head")
        assert "Running upgrade" not in second.stdout + second.stderr
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name"
            ), {"name": database_name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_ADMIN_URL"), reason="PostgreSQL admin URL not configured")
def test_dal89_database_upgrades_through_dal75_to_merge_head():
    admin_url = make_url(os.environ["TEST_POSTGRES_ADMIN_URL"])
    database_name = f"dal92_existing_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target_url = admin_url.set(database=database_name)
    env = os.environ.copy()
    env.update({
        "SQLALCHEMY_DATABASE_USER": admin_url.username or "",
        "SQLALCHEMY_DATABASE_PASSWORD": admin_url.password or "",
        "SQLALCHEMY_DATABASE_HOST": admin_url.host or "localhost",
        "SQLALCHEMY_DATABASE_PORT": str(admin_url.port or 5432),
        "SQLALCHEMY_DATABASE_DB": database_name,
    })

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        def run(*args):
            return subprocess.run(
                ["uv", "run", "alembic", *args], cwd=os.path.dirname(__file__) + "/..",
                env=env, check=True, capture_output=True, text=True,
            )

        run("upgrade", "dal89webauth01")
        with create_engine(target_url).connect() as connection:
            before = {column["name"] for column in inspect(connection).get_columns("coaching_sessions")}
            expected = {
                "candidate_insights", "insight_gate_decisions", "displayed_insight_ids", "insight_provenance",
            }
            assert not expected & before

        run("upgrade", "head")
        current = run("current").stdout
        assert "dal92merge01 (head)" in current
        with create_engine(target_url).connect() as connection:
            columns = {column["name"] for column in inspect(connection).get_columns("coaching_sessions")}
            assert expected <= columns
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name"
            ), {"name": database_name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()
