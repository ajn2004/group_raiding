import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def migration_module():
    path = Path(__file__).parents[2] / "alembic/versions/dal68_wipefest_snapshots.py"
    spec = importlib.util.spec_from_file_location("dal68_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_revision(connection, operation):
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        operation()


def test_dal68_revision_upgrades_persists_and_downgrades_in_isolated_sqlite():
    engine = create_engine("sqlite://")
    module = migration_module()
    with engine.begin() as connection:
        run_revision(connection, module.upgrade)
        inspector = inspect(connection)
        assert "wipefest_fight_snapshots" in inspector.get_table_names()
        constraints = inspector.get_unique_constraints("wipefest_fight_snapshots")
        assert any(item["column_names"] == [
            "provider", "report_code", "fight_id", "group_id", "fingerprint",
        ] for item in constraints)

        payload = {"events": [{"timestamp": 123, "ability": {"guid": 456}}]}
        connection.execute(text("""
            INSERT INTO wipefest_fight_snapshots
            (provider, report_code, fight_id, group_id, request_url, request_params,
             fetched_at, payload, fingerprint, response_status, response_etag)
            VALUES (:provider, :report_code, :fight_id, :group_id, :request_url,
                    :request_params, :fetched_at, :payload, :fingerprint,
                    :response_status, :response_etag)
        """), {
            "provider": "wipefest", "report_code": "reference", "fight_id": "10",
            "group_id": "1507", "request_url": "https://api.wipefest.gg/report/reference/fight/10",
            "request_params": '{"markupFormat":"Markup","group":"1507","insightsOnly":"false"}',
            "fetched_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "payload": '{"events":[{"timestamp":123,"ability":{"guid":456}}]}',
            "fingerprint": "a" * 64, "response_status": 200, "response_etag": '"etag"',
        })
        stored = connection.execute(text(
            "SELECT payload FROM wipefest_fight_snapshots WHERE report_code = 'reference'"
        )).scalar_one()
        assert '"guid":456' in stored

        run_revision(connection, module.downgrade)
        assert "wipefest_fight_snapshots" not in inspect(connection).get_table_names()
