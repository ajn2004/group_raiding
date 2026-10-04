import json
from pathlib import Path
import importlib
import sys
import types

import pytest

from app.pull_coach.mechanics.store import DirectoryMechanicsStore, MechanicsStoreError, configured_mechanics_registry
from app.pull_coach.models import (
    CandidateMechanic, DiscoveryProvenance, EncounterDiscovery, EventType, NormalizedEvent,
)
from app.pull_coach.workflow import PullCoachConfigurationError


SOURCE = Path("app/pull_coach/mechanics/definitions/example.json")


def definition(encounter_id, mechanic_id="blast", ability_id=42):
    document = json.loads(SOURCE.read_text())
    document["definitions"][0].update(
        encounter={"encounter_id": encounter_id, "name": encounter_id.title()},
        mechanic_id=mechanic_id,
        ability_ids=[ability_id],
    )
    return document


def discovery(encounter_id="1"):
    return EncounterDiscovery(
        encounter_id, "Boss", (DiscoveryProvenance("wcl", "a" * 64, "fight-1"),),
        (CandidateMechanic(42, "Blast", (EventType.DAMAGE,)),),
    )


def test_loads_verified_files_in_deterministic_order_and_ignores_other_lanes(tmp_path):
    store = DirectoryMechanicsStore(tmp_path)
    store.write_verified("2", definition("2"))
    store.write_verified("1", definition("1"))
    store.write_discovery(discovery("3"))
    store.write_draft("4", {"definitions": ["not analyzer input"]})

    registry = store.load_verified_registry()
    assert [item.encounter.encounter_id for item in registry.definitions] == ["1", "2"]
    assert [x.mechanic_id for x in registry.for_encounter(registry.definitions[0].encounter)] == ["blast"]
    assert [x.mechanic_id for x in registry.for_encounter(registry.definitions[1].encounter)] == ["blast"]
    assert "1.json" in registry.registry_version
    assert "2.json" in registry.registry_version


def test_aggregate_duplicate_and_selector_conflicts_include_sources(tmp_path):
    store = DirectoryMechanicsStore(tmp_path)
    store.write_verified("1", definition("1", "same", 42))
    # Bypass validated store writer to model an externally edited deployment.
    (tmp_path / "verified" / "b.json").write_text(json.dumps(definition("1", "same", 43)))
    with pytest.raises(MechanicsStoreError, match="duplicate mechanic_id.*1.json.*b.json"):
        store.load_verified_registry()

    (tmp_path / "verified" / "b.json").write_text(json.dumps(definition("1", "different", 42)))
    with pytest.raises(MechanicsStoreError, match="ambiguous"):
        store.load_verified_registry()


def test_malformed_file_is_actionable_and_new_file_visible_on_next_load(tmp_path):
    store = DirectoryMechanicsStore(tmp_path)
    store.write_verified("1", definition("1"))
    assert len(store.load_verified_registry().definitions) == 1
    replacement = definition("1", ability_id=43)
    with pytest.raises(MechanicsStoreError, match="replace=True"):
        store.write_verified("1", replacement)
    store.write_verified("1", replacement, replace=True)
    assert store.load_verified_registry().rules[0].definition.ability_ids == (43,)
    (tmp_path / "verified" / "broken.json").write_text('{"schema_version": 77}')
    with pytest.raises(MechanicsStoreError, match="broken.json.*unsupported"):
        store.load_verified_registry()


def test_discovery_round_trip_uses_canonical_codec(tmp_path):
    store = DirectoryMechanicsStore(tmp_path)
    expected = discovery()
    store.write_discovery(expected)
    assert store.read_discovery(expected.encounter_id) == expected


def test_write_failure_is_explicit(tmp_path, monkeypatch):
    store = DirectoryMechanicsStore(tmp_path)
    def fail(*args, **kwargs):
        raise PermissionError("read-only")
    monkeypatch.setattr("app.pull_coach.mechanics.store.os.replace", fail)
    with pytest.raises(MechanicsStoreError, match="cannot persist.*read-only"):
        store.write_draft("boss-1", {"draft": True})


def test_configuration_root_precedence_and_legacy_fallback(tmp_path, monkeypatch):
    root = tmp_path / "root"
    DirectoryMechanicsStore(root).write_verified("1", definition("1"))
    monkeypatch.setenv("PULL_COACH_MECHANICS_ROOT", str(root))
    monkeypatch.setenv("PULL_COACH_MECHANICS_FILE", "missing.json")
    assert len(configured_mechanics_registry().definitions) == 1

    monkeypatch.delenv("PULL_COACH_MECHANICS_ROOT")
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps(definition("2")))
    monkeypatch.setenv("PULL_COACH_MECHANICS_FILE", str(legacy))
    assert configured_mechanics_registry().definitions[0].encounter.encounter_id == "2"
    monkeypatch.delenv("PULL_COACH_MECHANICS_FILE")
    with pytest.raises(PullCoachConfigurationError):
        configured_mechanics_registry()

    missing_root = tmp_path / "does-not-exist"
    monkeypatch.setenv("PULL_COACH_MECHANICS_ROOT", str(missing_root))
    with pytest.raises(PullCoachConfigurationError, match="does not exist"):
        configured_mechanics_registry()


def test_checked_in_live_mechanics_root_loads_and_blank_root_allows_legacy(monkeypatch, tmp_path):
    checked_in_root = Path("mechanics/pull-coach")
    registry = DirectoryMechanicsStore(checked_in_root).load_verified_registry()
    assert registry.rules == ()
    assert {path.name for path in checked_in_root.iterdir()} == {
        "verified", "discovered", "drafts", "reviews",
    }

    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps(definition("2")))
    monkeypatch.setenv("PULL_COACH_MECHANICS_ROOT", "")
    monkeypatch.setenv("PULL_COACH_MECHANICS_FILE", str(legacy))
    assert configured_mechanics_registry().definitions[0].encounter.encounter_id == "2"


def test_verified_rules_retain_their_source_provenance(tmp_path):
    store = DirectoryMechanicsStore(tmp_path)
    store.write_verified("1", definition("1"))
    store.write_verified("2", definition("2"))
    registry = store.load_verified_registry()
    for rule in registry.rules:
        match = registry.match(rule.definition.encounter,
                               NormalizedEvent(1, EventType.DAMAGE, "e", ability_id=42))[0]
        assert match.source_artifact == f"verified/{rule.definition.encounter.encounter_id}.json"
        assert match.source_registry_version == "1"


def test_live_and_catalog_factories_share_registry_configuration(tmp_path, monkeypatch):
    # Bypass the legacy commands package initializer, which eagerly initializes
    # the unrelated guild database.
    package = types.ModuleType("app.discord_bot.commands")
    package.__path__ = [str(Path("app/discord_bot/commands").resolve())]
    monkeypatch.setitem(sys.modules, "app.discord_bot.commands", package)
    pull_coach = importlib.import_module("app.discord_bot.commands.pull_coach")

    root = tmp_path / "root"
    DirectoryMechanicsStore(root).write_verified("1", definition("1"))
    monkeypatch.setenv("PULL_COACH_MECHANICS_ROOT", str(root))
    monkeypatch.delenv("PULL_COACH_MECHANICS_FILE", raising=False)
    monkeypatch.setattr(pull_coach, "WCLClient", lambda: object())
    workflow = pull_coach._configured_workflow()
    catalog = pull_coach._configured_catalog_discovery()
    assert workflow.analyzer.registry.definitions == catalog.mechanic_registry.definitions
