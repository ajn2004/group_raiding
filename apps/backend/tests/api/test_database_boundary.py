"""Regression tests for the canonical runtime database boundary (DAL-90).

These tests must be runnable on their own, without a developer's ``.env``,
without PostgreSQL, and without any other test module having imported
``app.db.database`` first. ``app.db.database`` builds its engine at import time,
so tests that import it own their configuration explicitly.
"""

import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.pool import StaticPool

from app.api import auth_repository
from app.db.models import Base, CoachingProfile, OAuthState
from app.pull_coach.persistence.coaching_profiles import CoachingProfileRepository

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DUMMY_POSTGRES_CONFIG = {
    "SQLALCHEMY_DATABASE_USER": "dal90-test",
    "SQLALCHEMY_DATABASE_PASSWORD": "dal90-test",
    "SQLALCHEMY_DATABASE_HOST": "127.0.0.1",
    "SQLALCHEMY_DATABASE_PORT": "1",  # reserved/never-listening; engine construction does not connect
    "SQLALCHEMY_DATABASE_DB": "dal90_test",
}


def run_isolated(source: str, database_config: dict | None = None) -> subprocess.CompletedProcess:
    """Run `source` in a fresh interpreter with dotenv and .env disabled.

    The child's environment drops every SQLALCHEMY_DATABASE_* variable and stubs
    ``load_dotenv`` so a local .env cannot silently restore them. This proves the
    behavior without relying on, or modifying, developer configuration. Pass
    ``database_config`` to supply test-owned dummy values; no real connection is
    attempted because ``create_engine`` connects lazily.
    """
    preamble = textwrap.dedent(
        """
        import os
        for _name in [n for n in os.environ if n.startswith("SQLALCHEMY_DATABASE_")]:
            del os.environ[_name]
        import dotenv
        dotenv.load_dotenv = lambda *args, **kwargs: False
        """
    )
    for name, value in (database_config or {}).items():
        preamble += f"os.environ[{name!r}] = {value!r}\n"
    return subprocess.run(
        [sys.executable, "-c", preamble + textwrap.dedent(source)],
        cwd=BACKEND_ROOT, env=dict(os.environ), capture_output=True, text=True,
    )


def test_api_import_openapi_and_health_do_not_initialize_database():
    result = run_isolated(
        """
        from fastapi.testclient import TestClient
        from app.api.main import app

        import sys
        assert "app.db.database" not in sys.modules, "importing the API must not import the database module"
        assert app.openapi()
        assert TestClient(app).get("/api/healthz").status_code == 200
        assert "app.db.database" not in sys.modules
        """
    )
    assert result.returncode == 0, result.stderr


def test_database_dependency_closes_and_rolls_back_without_committing():
    """Real get_db_session()/session_scope() with only the factory replaced.

    A dummy PostgreSQL URL satisfies engine construction without connecting.
    """
    result = run_isolated(
        """
        created = []

        class RecordingSession:
            def __init__(self):
                self.closed = False
                self.rolled_back = False
                self.committed = False

            def close(self):
                self.closed = True

            def rollback(self):
                self.rolled_back = True

            def commit(self):
                self.committed = True

        from app.db import database

        def factory():
            session = RecordingSession()
            created.append(session)
            return session

        database.Session = factory
        engine = database.Engine
        assert engine.dialect.name == "postgresql"

        from app.api.dependencies import get_db_session

        # Success path: closes without committing, and no explicit rollback.
        generator = get_db_session()
        first = next(generator)
        assert first is created[0]
        try:
            next(generator)
        except StopIteration:
            pass
        else:
            raise AssertionError("dependency must finish after the response")
        assert first.closed, "success must close the session"
        assert not first.committed, "success must not commit implicitly"
        assert not first.rolled_back, "success must not roll back explicitly"

        # Failure path: rollback and close, original exception propagates.
        generator = get_db_session()
        second = next(generator)
        assert second is created[1] and second is not first, "sessions must be per-invocation"
        try:
            generator.throw(RuntimeError("request failed"))
        except RuntimeError as exc:
            assert str(exc) == "request failed"
        else:
            raise AssertionError("the original exception must propagate")
        assert second.rolled_back, "failure must roll back"
        assert second.closed, "failure must close the session"
        assert not second.committed, "failure must not commit"

        # The shared engine is reused; no engine is created per request.
        assert database.Engine is engine
        engine.dispose()
        print("OK")
        """,
        DUMMY_POSTGRES_CONFIG,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_database_url_quotes_special_credential_characters(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "USERNAME", "user@realm/name")
    monkeypatch.setattr(config, "PASSWORD", "p@ss:/word")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_HOST", "localhost")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_PORT", "5432")
    monkeypatch.setattr(config, "DB_NAME", "guild")

    url = config.database_url()
    assert url.username == "user@realm/name"
    assert url.password == "p@ss:/word"
    assert url.host == "localhost"
    assert url.database == "guild"


@pytest.fixture
def isolated_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _write_auth_state(session: SQLAlchemySession, digest: str) -> None:
    auth_repository.create_state(
        session, digest, "/safe/path",
        datetime.now(timezone.utc) + timedelta(minutes=10),
    )


def _write_coaching_revision(session: SQLAlchemySession, purpose: str) -> None:
    CoachingProfileRepository(session).create_revision(
        purpose, provider="openrouter", model_slug="vendor/model-a",
        system_prompt="system a", user_prompt_template="user a",
        output_schema_version="selection-v1",
    )


def test_auth_and_existing_repository_share_one_rolled_back_transaction(isolated_engine):
    """Both writes must vanish together unless the caller commits."""
    session = SQLAlchemySession(isolated_engine, expire_on_commit=False)
    _write_auth_state(session, "digest-rollback")
    _write_coaching_revision(session, "purpose-rollback")
    session.flush()  # both writes are really in the transaction now
    assert session.scalar(select(OAuthState).where(OAuthState.state_digest == "digest-rollback"))
    assert session.scalar(select(CoachingProfile).where(CoachingProfile.purpose == "purpose-rollback"))
    session.rollback()
    session.close()

    with SQLAlchemySession(isolated_engine) as verify:
        assert verify.scalar(select(OAuthState)) is None
        assert verify.scalar(select(CoachingProfile)) is None


def test_auth_and_existing_repository_persist_only_after_caller_commit(isolated_engine):
    session = SQLAlchemySession(isolated_engine, expire_on_commit=False)
    _write_auth_state(session, "digest-commit")
    _write_coaching_revision(session, "purpose-commit")
    session.flush()
    session.commit()
    session.close()

    with SQLAlchemySession(isolated_engine) as verify:
        assert verify.scalar(select(OAuthState).where(OAuthState.state_digest == "digest-commit"))
        assert verify.scalar(select(CoachingProfile).where(CoachingProfile.purpose == "purpose-commit"))


def test_auth_and_existing_repository_share_the_canonical_session_wrapper():
    """The shared wrapper drives both repositories through one caller transaction.

    Runs in isolation so importing the canonical module never depends on another
    test's configuration; only the session factory is replaced, with an isolated
    temporary SQLite database standing in for runtime PostgreSQL.
    """
    result = run_isolated(
        """
        import os
        import tempfile
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from app.db.models import Base, CoachingProfile, OAuthState
        from app.api import auth_repository
        from app.pull_coach.persistence.coaching_profiles import CoachingProfileRepository

        from app.db import database

        def auth_writer(session, digest):
            auth_repository.create_state(
                session, digest, "/safe/path", datetime.now(timezone.utc) + timedelta(minutes=10))

        def coach_writer(session, purpose):
            CoachingProfileRepository(session).create_revision(
                purpose, provider="openrouter", model_slug="vendor/model-a",
                system_prompt="system a", user_prompt_template="user a",
                output_schema_version="selection-v1")

        def exercise(path):
            engine = create_engine("sqlite:///" + path)
            verify_engine = None
            try:
                Base.metadata.create_all(engine)

                # Reuse the canonical wrapper; replace only how it obtains a session.
                database.Session = lambda: Session(engine, expire_on_commit=False)

                # Caller failure must roll back both repositories' writes together.
                try:
                    with database.session_scope() as session:
                        auth_writer(session, "digest-wrapper-rollback")
                        coach_writer(session, "purpose-wrapper-rollback")
                        raise RuntimeError("caller failed")
                except RuntimeError:
                    pass

                # Caller commit must persist both repositories' writes together.
                with database.session_scope() as session:
                    auth_writer(session, "digest-wrapper-commit")
                    coach_writer(session, "purpose-wrapper-commit")
                    session.commit()

                # Verify through a newly created engine after closing all sessions.
                engine.dispose()
                verify_engine = create_engine("sqlite:///" + path)
                with Session(verify_engine) as verify:
                    assert verify.scalar(select(OAuthState).where(
                        OAuthState.state_digest == "digest-wrapper-commit")) is not None
                    assert verify.scalar(select(CoachingProfile).where(
                        CoachingProfile.purpose == "purpose-wrapper-commit")) is not None
                    assert verify.scalar(select(OAuthState).where(
                        OAuthState.state_digest == "digest-wrapper-rollback")) is None
                    assert verify.scalar(select(CoachingProfile).where(
                        CoachingProfile.purpose == "purpose-wrapper-rollback")) is None
            finally:
                # Sessions are closed by their context managers; dispose both
                # engines here so the database file can be removed on any exit.
                if verify_engine is not None:
                    verify_engine.dispose()
                engine.dispose()

        # TemporaryDirectory removes the directory and its database file on both
        # normal and exceptional exits.
        with tempfile.TemporaryDirectory() as directory:
            database_path = os.path.join(directory, "shared-transaction.db")
            exercise(database_path)
            assert os.path.exists(database_path)
        assert not os.path.exists(directory), "temporary database directory must be removed"
        print("OK")
        """,
        DUMMY_POSTGRES_CONFIG,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout