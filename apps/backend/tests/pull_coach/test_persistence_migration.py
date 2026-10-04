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


def test_dal72_revision_upgrades_and_downgrades_after_dal70():
    engine = create_engine("sqlite://")
    versions = Path(__file__).parents[2] / "alembic/versions"
    modules = []
    for name, filename in (("dal46", "dal46_pull_coach_persistence.py"),
                           ("dal68", "dal68_wipefest_snapshots.py"),
                           ("dal70", "dal70_coaching_profiles.py"),
                           ("dal72", "dal72_coaching_sessions.py")):
        spec = importlib.util.spec_from_file_location(name, versions / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE players (id INTEGER PRIMARY KEY)")
        for module in modules:
            run_revision(connection, module.upgrade)
        inspector = inspect(connection)
        assert {"coaching_sessions", "coaching_session_messages"}.issubset(inspector.get_table_names())
        assert {"snapshot_id", "profile_revision_id"}.issubset(
            {fk["constrained_columns"][0] for fk in inspector.get_foreign_keys("coaching_sessions")})
        checks = {item["name"] for item in inspector.get_check_constraints("coaching_sessions")}
        assert {"ck_coaching_session_audience", "ck_coaching_session_status", "ck_coaching_session_target"} <= checks
        message_checks = {item["name"] for item in inspector.get_check_constraints("coaching_session_messages")}
        assert {"ck_coaching_session_message_role", "ck_coaching_session_message_sequence"} <= message_checks
        assert {"ix_coaching_sessions_snapshot", "ix_coaching_sessions_fight"} <= {
            index["name"] for index in inspector.get_indexes("coaching_sessions")}
        assert any(item["column_names"] == ["session_id", "sequence"]
                   for item in inspector.get_unique_constraints("coaching_session_messages"))

        connection.exec_driver_sql("INSERT INTO wipefest_fight_snapshots "
            "(provider, report_code, fight_id, group_id, request_url, request_params, fetched_at, payload, fingerprint) "
            "VALUES ('wipefest', 'R1', 'F1', 'G1', 'https://example.test', '{}', CURRENT_TIMESTAMP, '{}', 'abc')")
        connection.exec_driver_sql("INSERT INTO coaching_sessions "
            "(snapshot_id, report_code, fight_id, encounter_id, audience, context_schema_version, "
            "context_fingerprint, request_context, profile_revision_id, provider, requested_model, status) "
            "VALUES (1, 'R1', 'F1', 'boss', 'raid', 'v1', 'abc', '{}', 1, 'openrouter', 'model', 'pending')")
        connection.exec_driver_sql("INSERT INTO coaching_session_messages "
            "(session_id, sequence, role, content) VALUES (1, 0, 'user', 'hello')")
        run_revision(connection, modules[3].downgrade)
        tables = set(inspect(connection).get_table_names())
        assert "coaching_sessions" not in tables and "coaching_session_messages" not in tables
        assert {"coaching_profiles", "coaching_profile_revisions"} <= tables


def test_dal75_insight_columns_upgrade_persist_json_and_downgrade_to_dal72():
    engine = create_engine("sqlite://")
    versions = Path(__file__).parents[2] / "alembic/versions"
    modules = []
    for name, filename in (("dal46", "dal46_pull_coach_persistence.py"),
                           ("dal68", "dal68_wipefest_snapshots.py"),
                           ("dal70", "dal70_coaching_profiles.py"),
                           ("dal72", "dal72_coaching_sessions.py"),
                           ("dal75", "dal75_insight_gate.py")):
        spec = importlib.util.spec_from_file_location(name, versions / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE players (id INTEGER PRIMARY KEY)")
        for module in modules:
            run_revision(connection, module.upgrade)
        expected = {"candidate_insights", "insight_gate_decisions", "displayed_insight_ids", "insight_provenance"}
        assert expected <= {column["name"] for column in inspect(connection).get_columns("coaching_sessions")}
        connection.exec_driver_sql("INSERT INTO wipefest_fight_snapshots "
            "(provider, report_code, fight_id, group_id, request_url, request_params, fetched_at, payload, fingerprint) "
            "VALUES ('wipefest', 'R1', 'F1', 'G1', 'https://example.test', '{}', CURRENT_TIMESTAMP, '{}', 'abc')")
        connection.exec_driver_sql(
            "INSERT INTO coaching_sessions "
            "(snapshot_id, report_code, fight_id, encounter_id, audience, context_schema_version, "
            "context_fingerprint, request_context, profile_revision_id, provider, requested_model, status, "
            "candidate_insights, insight_gate_decisions, displayed_insight_ids, insight_provenance) "
            "VALUES (1, 'R1', 'F1', 'boss', 'raid', 'v1', 'abc', '{}', 1, 'openrouter', 'model', 'completed', ?, ?, ?, ?)",
            ('[{"id": "candidate-1"}]', '[{"surface": false}]', '[]', '{"gate": "threshold"}'))
        stored = connection.exec_driver_sql("SELECT candidate_insights, insight_gate_decisions, "
            "displayed_insight_ids, insight_provenance FROM coaching_sessions WHERE id = 1").one()
        assert stored == ('[{"id": "candidate-1"}]', '[{"surface": false}]', '[]', '{"gate": "threshold"}')
        run_revision(connection, modules[4].downgrade)
        columns = {column["name"] for column in inspect(connection).get_columns("coaching_sessions")}
        assert expected.isdisjoint(columns)
        assert {"coaching_sessions", "coaching_session_messages", "coaching_profiles"} <= set(inspect(connection).get_table_names())
