import json

import pytest

from app.pull_coach.models.contracts import EventType
from app.pull_coach.models.discovery import (
    ActorType,
    CandidateMechanic,
    DiscoveryProvenance,
    EncounterDiscovery,
    LifecycleStage,
    discovery_from_json,
    discovery_to_json,
)


def sample_discovery():
    return EncounterDiscovery(
        encounter_id="2717",
        encounter_name="Example Boss",
        provenance=(DiscoveryProvenance("wcl", "a" * 64, "42"),),
        candidates=(CandidateMechanic(
            ability_id=1234,
            ability_name="Arcane Burst",
            event_types=(EventType.CAST, EventType.DAMAGE),
            source_actor_type_counts=((ActorType.NPC, 2),),
            target_actor_type_counts=((ActorType.PLAYER, 5),),
            fight_occurrence_counts=(("42", 8),),
            damage_total=1200.0,
            first_timestamp=100,
            last_timestamp=900,
            death_window_observations=2,
        ),),
    )


def test_discovery_json_is_stable_and_round_trips():
    document = discovery_to_json(sample_discovery())
    assert document == discovery_to_json(discovery_from_json(document))
    assert json.loads(document)["schema_version"] == 1
    assert document == discovery_to_json(sample_discovery())


def test_discovery_does_not_encode_coaching_semantics_or_personal_identity():
    document = discovery_to_json(sample_discovery())
    for forbidden in ("failure_category", "avoidable", "severity", "role", "exposure", "player_name", "metadata"):
        assert forbidden not in document


@pytest.mark.parametrize("document", [
    '{"schema_version":2}',
    '{"schema_version":1,"encounter_id":"1"}',
    '{"schema_version":true}',
])
def test_discovery_rejects_unsupported_or_malformed_documents(document):
    with pytest.raises(ValueError):
        discovery_from_json(document)


def test_candidate_lifecycle_starts_unverified():
    assert LifecycleStage.UNKNOWN.value == "unknown"
    assert LifecycleStage.DISCOVERED.value == "discovered"
    assert LifecycleStage.DRAFTED.value == "drafted"
    assert LifecycleStage.VERIFIED.value == "verified"
    assert LifecycleStage.SUPPORTED.value == "supported"
    assert sample_discovery().stage is LifecycleStage.DISCOVERED


@pytest.mark.parametrize("value", ["042", "0", "foo", 42, True])
def test_encounter_id_requires_canonical_positive_string(value):
    with pytest.raises(ValueError, match="canonical"):
        EncounterDiscovery(value, "Boss", (), ())


def test_encounter_id_accepts_canonical_string():
    assert EncounterDiscovery("42", "Boss", (), ()).encounter_id == "42"


@pytest.mark.parametrize("kwargs", [
    {"event_types": (123,)},
    {"source_actor_type_counts": (("AndrewsCharacter", 6),)},
    {"source_actor_type_counts": ((ActorType.NPC, 1.5),)},
    {"source_actor_type_counts": ((ActorType.NPC, 1), (ActorType.NPC, 2))},
    {"death_window_observations": 2.7},
    {"death_window_observations": None},
    {"damage_total": True},
    {"damage_total": float("nan")},
    {"ability_name": 123},
])
def test_candidate_rejects_malformed_values(kwargs):
    base = dict(ability_id=1, ability_name="A", event_types=(EventType.DAMAGE,))
    with pytest.raises(ValueError):
        CandidateMechanic(**(base | kwargs))


def test_json_rejects_non_finite_and_duplicate_keys():
    document = discovery_to_json(sample_discovery())
    with pytest.raises(ValueError):
        discovery_from_json(document.replace("1200.0", "NaN"))
    with pytest.raises(ValueError):
        discovery_from_json(document.replace('"schema_version":1', '"schema_version":1,"schema_version":1'))


def test_candidate_ability_identity_must_be_unique():
    candidate = sample_discovery().candidates[0]
    with pytest.raises(ValueError, match="unique"):
        EncounterDiscovery("42", "Boss", (), (candidate, candidate))


def test_numeric_ability_ids_are_canonical_across_integer_and_string_inputs():
    integer_id = CandidateMechanic(140495, "A", (EventType.DAMAGE,))
    string_id = CandidateMechanic("140495", "A", (EventType.DAMAGE,))
    assert integer_id.ability_id == string_id.ability_id == "140495"
    with pytest.raises(ValueError, match="unique"):
        EncounterDiscovery("42", "Boss", (), tuple(sorted((integer_id, string_id), key=lambda c: c.ability_id)))
