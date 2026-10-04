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


def test_dal70_revision_seeds_active_profiles_and_downgrades_in_isolated_sqlite():
    engine = create_engine("sqlite://")
    dal46 = migration_module()
    dal68_path = Path(__file__).parents[2] / "alembic/versions/dal68_wipefest_snapshots.py"
    dal68_spec = importlib.util.spec_from_file_location("dal68_migration", dal68_path)
    dal68 = importlib.util.module_from_spec(dal68_spec)
    dal68_spec.loader.exec_module(dal68)
    dal70_path = Path(__file__).parents[2] / "alembic/versions/dal70_coaching_profiles.py"
    spec = importlib.util.spec_from_file_location("dal70_migration", dal70_path)
    dal70 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dal70)

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE players (id INTEGER PRIMARY KEY)")
        run_revision(connection, dal46.upgrade)
        run_revision(connection, dal68.upgrade)
        run_revision(connection, dal70.upgrade)

        rows = connection.exec_driver_sql(
            "SELECT p.purpose, p.active_revision_id, r.id, r.revision "
            "FROM coaching_profiles AS p "
            "JOIN coaching_profile_revisions AS r ON r.id = p.active_revision_id "
            "ORDER BY p.purpose"
        ).all()
        assert [(purpose, revision) for purpose, _, _, revision in rows] == [
            ("insight_gate", 1), ("player_coach", 1), ("raid_coach", 1)
        ]
        assert all(active_revision == revision_id for _, active_revision, revision_id, _ in rows)

        run_revision(connection, dal70.downgrade)
        run_revision(connection, dal68.downgrade)
        tables = set(inspect(connection).get_table_names())
        assert "coaching_profiles" not in tables
        assert "coaching_profile_revisions" not in tables
        assert "profile_revision_id" not in {
            column["name"] for column in inspect(connection).get_columns("pull_coach_coaching_outputs")
        }
