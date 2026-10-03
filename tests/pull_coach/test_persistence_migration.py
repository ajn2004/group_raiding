import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def migration_module():
    path = Path(__file__).parents[2] / "alembic/versions/dal46_pull_coach_persistence.py"
    spec = importlib.util.spec_from_file_location("dal46_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_revision(connection, operation):
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        operation()


def test_dal46_revision_upgrades_and_downgrades_in_isolated_sqlite():
    engine = create_engine("sqlite://")
    module = migration_module()
    with engine.begin() as connection:
        # The legacy migration chain is deliberately not run: one historical
        # revision creates tables through the production Engine directly.
        connection.exec_driver_sql("CREATE TABLE players (id INTEGER PRIMARY KEY)")
        run_revision(connection, module.upgrade)
        inspector = inspect(connection)
        expected = {
            "pull_coach_reports", "pull_coach_pulls", "pull_coach_analyses",
            "pull_coach_findings", "pull_coach_evidence", "pull_coach_coaching_outputs",
        }
        assert expected.issubset(inspector.get_table_names())
        constraints = inspector.get_unique_constraints("pull_coach_reports")
        assert any(item["column_names"] == ["scope", "provider", "report_code"]
                   for item in constraints)
        assert any(item["column_names"] == ["report_id", "fight_id"]
                   for item in inspector.get_unique_constraints("pull_coach_pulls"))
        assert "players" in inspect(connection).get_table_names()
        run_revision(connection, module.downgrade)
        assert expected.isdisjoint(inspect(connection).get_table_names())
        assert "players" in inspect(connection).get_table_names()
