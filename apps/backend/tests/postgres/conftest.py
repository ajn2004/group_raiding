"""Opt-in PostgreSQL integration-test infrastructure."""
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def postgres_database(request):
    if not request.config.getoption("--postgres"):
        pytest.fail("PostgreSQL tests require --postgres", pytrace=False)
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        pytest.fail("PostgreSQL lane requires TEST_DATABASE_URL; set it to a disposable PostgreSQL database URL", pytrace=False)
    try:
        base_url = make_url(raw_url)
    except Exception:
        pytest.fail("TEST_DATABASE_URL is invalid; expected a PostgreSQL URL (credentials are not displayed)", pytrace=False)
    if base_url.get_backend_name() != "postgresql":
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL; SQLite and other dialects are not accepted", pytrace=False)

    schema = "dal91_test_" + uuid.uuid4().hex
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    isolated_engine = None
    created = False
    try:
        try:
            with admin_engine.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        except SQLAlchemyError:
            pytest.fail("Could not connect/create an isolated schema using TEST_DATABASE_URL; start the disposable PostgreSQL service and verify its test-user permissions (URL hidden)", pytrace=False)
        scoped_url = base_url.update_query_dict({"options": f"-csearch_path={schema}"})
        isolated_engine = create_engine(scoped_url, pool_pre_ping=True)
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.attributes["version_table_schema"] = schema
        # ConfigParser treats '%' specially; preserve escaped credentials without
        # ever emitting the URL in test diagnostics.
        alembic_cfg.set_main_option(
            "sqlalchemy.url", scoped_url.render_as_string(hide_password=False).replace("%", "%%")
        )
        scripts = ScriptDirectory.from_config(alembic_cfg)
        expected_head = scripts.get_current_head()
        command.upgrade(alembic_cfg, "head")
        with isolated_engine.connect() as conn:
            current_revision = conn.execute(
                text(f'SELECT version_num FROM "{schema}".alembic_version')
            ).scalar_one()
            assert current_revision == expected_head
        yield {
            "engine": isolated_engine,
            "sessions": sessionmaker(bind=isolated_engine, expire_on_commit=False),
            "schema": schema,
            "base_url": base_url,
            "url": scoped_url,
            "alembic_config": alembic_cfg,
            "head": expected_head,
        }
    finally:
        try:
            if isolated_engine is not None:
                isolated_engine.dispose()
        finally:
            try:
                if created:
                    with admin_engine.begin() as conn:
                        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            finally:
                admin_engine.dispose()
