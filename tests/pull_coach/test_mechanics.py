import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.pull_coach.fixtures import load_pull_fixture
from app.pull_coach.mechanics import (
    FailureCategory,
    MechanicRegistry,
    MechanicSchemaError,
    UnsupportedMechanicSchemaVersion,
    load_mechanic_registry,
    load_mechanic_definitions,
)
from app.pull_coach.models import EncounterIdentity, EventType, NormalizedEvent


DEFINITIONS = Path(__file__).parents[2] / "app/pull_coach/mechanics/definitions"
FIXTURES = Path(__file__).parents[2] / "app/pull_coach/fixtures/example"


def test_failure_category_values_are_stable():
    assert {category.value for category in FailureCategory} == {
        "avoidable_damage", "unavoidable_damage", "healing_check", "positioning",
        "interrupt", "dispel", "target_priority", "tank_execution",
        "cooldown_or_resource", "assignment",
    }


def test_reference_fixture_event_matches_mechanic_definition():
    pull = load_pull_fixture(FIXTURES / "pull-1.json")
    registry = MechanicRegistry(load_mechanic_definitions(DEFINITIONS / "example.json"))

    matches = registry.match(pull.pull.encounter, pull.events[0])

    assert len(matches) == 1
    assert matches[0].definition.mechanic_id == "example-blast"
    assert matches[0].definition.failure_category == "avoidable_damage"
    assert matches[0].definition.avoidable is True


def test_canonical_loader_preserves_registry_version_into_matches(tmp_path):
    payload = json.loads((DEFINITIONS / "example.json").read_text())
    payload["registry_version"] = "7"
    path = tmp_path / "versioned.json"
    path.write_text(json.dumps(payload))
    registry = load_mechanic_registry(path)
    match = registry.match(EncounterIdentity("boss-1", "Example Encounter"),
                          NormalizedEvent(1, EventType.DAMAGE, "e", ability_id=42))[0]
    assert registry.registry_version == match.registry_version == "7"
    assert match.source_artifact == str(path)
    assert match.source_registry_version == "7"


def test_reference_wcl_snapshot_ingests_and_matches_mechanic():
    from app.web_requests.warcraft_logs import WCLClient, WCLSnapshot
    snapshot = WCLSnapshot.load(Path(__file__).parents[1] / "fixtures/warcraft_logs/reference_snapshot.json")
    ingestion = WCLClient().ingest_fight(snapshot, "REFERENCE01", 7)
    registry = load_mechanic_registry(DEFINITIONS / "reference_wcl.json")
    matches = registry.match(ingestion.pull.encounter, ingestion.events[1])
    assert [match.definition.mechanic_id for match in matches] == ["reference-bolt"]
    assert matches[0].definition.failure_category == "avoidable_damage"
    assert matches[0].registry_version == "reference-1"


def test_encounter_matching_uses_id_not_display_name():
    registry = load_mechanic_registry(DEFINITIONS / "example.json")
    event = NormalizedEvent(1, EventType.DAMAGE, "e", ability_id=42)
    assert len(registry.match(EncounterIdentity("boss-1", "Renamed boss"), event)) == 1
    assert registry.for_encounter(EncounterIdentity("boss-1", "Renamed boss"))
    assert registry.match(EncounterIdentity("boss-2", "Example Encounter"), event) == ()


def test_nested_metadata_predicate_is_rejected_explicitly():
    payload = json.loads((DEFINITIONS / "example.json").read_text())
    payload["definitions"][0]["metadata_predicates"] = {"phase": {"number": 1}}
    from app.pull_coach.mechanics.loader import definitions_from_dict
    with pytest.raises(MechanicSchemaError, match="scalar"):
        definitions_from_dict(payload)


def test_ability_and_stopped_ability_selectors_are_conjunctive():
    payload = {"schema_version": 1, "registry_version": "1", "definitions": [{
        "encounter": {"encounter_id": "42", "name": "Boss"}, "mechanic_id": "kick-shadowbolt",
        "name": "Kick Shadow Bolt", "event_types": ["interrupt"], "ability_ids": [1766],
        "stopped_ability_ids": [12345], "stopped_ability_metadata_field": "stopped_ability_id",
        "failure_category": "interrupt"}]}
    from app.pull_coach.mechanics.loader import registry_from_dict
    registry = registry_from_dict(payload)
    encounter = EncounterIdentity("42", "Boss")
    def interrupt(ability, stopped):
        return NormalizedEvent(1, EventType.INTERRUPT, str(ability), ability_id=ability,
                               metadata={"stopped_ability_id": stopped})
    assert registry.match(encounter, interrupt(1766, 12345))
    assert registry.match(encounter, interrupt(1766, 54321)) == ()
    assert registry.match(encounter, interrupt(6552, 12345)) == ()
    assert registry.match(encounter, interrupt(9999, 8888)) == ()


def test_loader_rejects_malformed_and_unsupported_documents(tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema_version":1,"mechanics":[]}')
    with pytest.raises(MechanicSchemaError):
        load_mechanic_definitions(malformed)

    future = tmp_path / "future.json"
    future.write_text(json.dumps({"schema_version": 99, "definitions": []}))
    with pytest.raises(UnsupportedMechanicSchemaVersion):
        load_mechanic_definitions(future)


def test_matching_is_encounter_event_and_ability_specific():
    definitions = load_mechanic_definitions(DEFINITIONS / "example.json")
    registry = MechanicRegistry(definitions)
    encounter = EncounterIdentity("boss-1", "Example Encounter")
    other = EncounterIdentity("boss-2", "Other Encounter")
    event = NormalizedEvent(1, EventType.DAMAGE, "e1", ability_id=42)

    assert len(registry.match(encounter, event)) == 1
    assert registry.match(other, event) == ()
    assert registry.match(encounter, NormalizedEvent(1, EventType.CAST, "e2", ability_id=42)) == ()
    assert registry.match(encounter, NormalizedEvent(1, EventType.DAMAGE, "e3", ability_id=999)) == ()
    assert registry.match(EncounterIdentity("unknown", "Unknown"), event) == ()


def test_stopped_ability_uses_metadata_field_not_event_ability():
    path = DEFINITIONS / "example.json"
    registry = MechanicRegistry(load_mechanic_definitions(path))
    interrupt_rule = {
        "mechanic_id": "interrupt-target", "name": "Interrupt target",
        "encounter": {"encounter_id": "boss-1", "name": "Example Encounter"},
        "event_types": ["interrupt"], "stopped_ability_ids": [700],
        "failure_category": "interrupt", "avoidable": None,
        "expected_roles": ["damage"], "severity": "medium",
        "stopped_ability_metadata_field": "stopped_ability_id",
    }
    payload = json.loads(path.read_text())
    payload["definitions"].append(interrupt_rule)
    from app.pull_coach.mechanics.loader import definitions_from_dict

    registry = MechanicRegistry(definitions_from_dict(payload))
    event = NormalizedEvent(2, EventType.INTERRUPT, "i1", ability_id=99,
                            metadata={"stopped_ability_id": 700})
    assert [match.definition.mechanic_id for match in registry.match(
        EncounterIdentity("boss-1", "Example Encounter"), event
    )] == ["interrupt-target"]
    unknown = NormalizedEvent(2, EventType.INTERRUPT, "i2", ability_id=99,
                              metadata={"stopped_ability_id": 701})
    assert registry.match(EncounterIdentity("boss-1", "Example Encounter"), unknown) == ()


def test_match_order_is_stable_and_duplicate_rules_fail():
    payload = json.loads((DEFINITIONS / "example.json").read_text())
    duplicate = dict(payload["definitions"][0], mechanic_id="example-blast-lower", weight=0.5,
                     metadata_predicates={"phase": 1})
    payload["definitions"].append(duplicate)
    from app.pull_coach.mechanics.loader import definitions_from_dict

    registry = MechanicRegistry(definitions_from_dict(payload))
    encounter = EncounterIdentity("boss-1", "Example Encounter")
    event = NormalizedEvent(1, EventType.DAMAGE, "e1", ability_id=42, metadata={"phase": 1})
    first = registry.match(encounter, event)
    assert [m.definition.mechanic_id for m in first] == ["example-blast", "example-blast-lower"]
    assert registry.match(encounter, event) == first

    payload["definitions"].append(payload["definitions"][0])
    with pytest.raises(MechanicSchemaError, match="duplicate mechanic_id"):
        definitions_from_dict(payload)

    ambiguous = json.loads((DEFINITIONS / "example.json").read_text())
    ambiguous["definitions"].append(dict(
        ambiguous["definitions"][0], mechanic_id="same-selector"
    ))
    with pytest.raises(MechanicSchemaError, match="ambiguous duplicate"):
        definitions_from_dict(ambiguous)


@pytest.mark.parametrize("selector_key", ["ability_ids", "stopped_ability_ids"])
def test_reordered_equivalent_selectors_are_ambiguous(selector_key):
    payload = {
        "schema_version": 1,
        "definitions": [{
            "encounter": {"encounter_id": "42", "name": "Boss"},
            "mechanic_id": "first", "name": "First", "event_types": ["interrupt"],
            "ability_ids": [10], "stopped_ability_ids": [20, 30],
            "stopped_ability_metadata_field": "stopped_ability_id",
            "failure_category": "interrupt",
        }, {
            "encounter": {"encounter_id": "42", "name": "Boss"},
            "mechanic_id": "second", "name": "Second", "event_types": ["interrupt"],
            "ability_ids": [10], "stopped_ability_ids": [20, 30],
            "stopped_ability_metadata_field": "stopped_ability_id",
            "failure_category": "interrupt",
        }],
    }
    payload["definitions"][1][selector_key] = list(reversed(payload["definitions"][1][selector_key]))
    from app.pull_coach.mechanics.loader import definitions_from_dict

    with pytest.raises(MechanicSchemaError, match="ambiguous duplicate"):
        definitions_from_dict(payload)


@pytest.mark.parametrize(("selector_key", "event_type", "first", "second"), [
    ("ability_ids", "damage", [12345], ["12345"]),
    ("ability_ids", "damage", [12345], ["012345"]),
    ("stopped_ability_ids", "interrupt", [12345], ["12345"]),
    ("stopped_ability_ids", "interrupt", [12345], ["012345"]),
])
def test_numeric_selector_representations_are_ambiguous(selector_key, event_type, first, second):
    definitions = []
    for mechanic_id, selectors in (("first", first), ("second", second)):
        definition = {
            "encounter": {"encounter_id": "42", "name": "Boss"},
            "mechanic_id": mechanic_id, "name": mechanic_id.title(), "event_types": [event_type],
            "failure_category": "interrupt" if event_type == "interrupt" else "avoidable_damage",
        }
        if selector_key == "ability_ids":
            definition["ability_ids"] = selectors
        else:
            definition.update(stopped_ability_ids=selectors,
                              stopped_ability_metadata_field="stopped_ability_id")
        definitions.append(definition)
    from app.pull_coach.mechanics.loader import definitions_from_dict

    with pytest.raises(MechanicSchemaError, match="ambiguous duplicate"):
        definitions_from_dict({"schema_version": 1, "definitions": definitions})


def test_rule_metadata_preserves_timing_and_relationships():
    definition = load_mechanic_definitions(DEFINITIONS / "example.json")[0]
    assert definition.definition_version == "1"
    assert definition.definition.timing_window.start_offset_ms == 100
    assert definition.relationships == {"pairs_with": ["defensive-cooldown"]}


def test_exposure_selector_is_explicit_and_legacy_definition_remains_unknown():
    from app.pull_coach.analysis import PullAnalyzer
    from app.pull_coach.models import ExposureState
    from app.pull_coach.progression import ProgressionComparator
    from app.pull_coach.mechanics.loader import registry_from_dict

    payload = {"schema_version": 1, "definitions": [{
        "encounter": {"encounter_id": "42", "name": "Boss"}, "mechanic_id": "maze",
        "name": "Maze", "event_types": ["damage"], "ability_ids": [10],
        "failure_category": "positioning", "avoidable": True,
        "exposure": {"event_types": ["cast"], "ability_ids": [11]},
    }]}
    registry = registry_from_dict(payload)
    pull = load_pull_fixture(FIXTURES / "pull-1.json").pull
    pull = replace(pull, encounter=EncounterIdentity("42", "Boss"))
    events = [NormalizedEvent(10, EventType.CAST, "opportunity", ability_id=11)]
    analyzed = PullAnalyzer(registry).analyze(pull, (), events)
    assert analyzed.mechanic_exposures[0].state == ExposureState.EXPOSED
    assert analyzed.mechanic_exposures[0].opportunity_count == 1
    assert analyzed.mechanic_exposures[0].evidence[0].evidence_id == "opportunity"
    not_reached = PullAnalyzer(registry).analyze(pull, (), ())
    assert not_reached.mechanic_exposures[0].state == ExposureState.NOT_EXPOSED

    del payload["definitions"][0]["exposure"]
    legacy = PullAnalyzer(registry_from_dict(payload)).analyze(pull, (), ())
    assert legacy.mechanic_exposures[0].state == ExposureState.UNKNOWN
    assert not any(s.subject_id == "mechanic:maze" for s in ProgressionComparator().compare([legacy]).subjects)
