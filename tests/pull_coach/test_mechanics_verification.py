import json
from datetime import datetime, timezone

import pytest

from app.pull_coach.mechanics.store import DirectoryMechanicsStore, MechanicsStoreError
from app.pull_coach.mechanics.verification import MechanicVerificationService, VerifiedMechanicInput
from app.pull_coach.models import (
    CandidateMechanic, DiscoveryProvenance, EncounterDiscovery, EncounterIdentity,
    EventType, NormalizedEvent,
)


def setup_store(path, *, draft=False):
    store = DirectoryMechanicsStore(path)
    store.write_discovery(EncounterDiscovery("1", "Boss", (DiscoveryProvenance("wcl", "a" * 64, "fight-1"),),
        (CandidateMechanic(42, "Blast", (EventType.DAMAGE,), fight_occurrence_counts=(("fight-1", 3),)),)))
    if draft:
        store.write_draft("1", {"candidates": [{"candidate_id": "1:42", "proposal": {"failure_category": "positioning", "provider": "test"}}]})
    return store


def data(**overrides):
    values = dict(mechanic_id="blast", name="Blast", failure_category="avoidable_damage", severity="high",
                  avoidability="true", expected_roles=("damage",), selector_interpretation="observed_ability", reviewer="operator")
    values.update(overrides)
    return VerifiedMechanicInput(**values)


def test_review_is_fact_only_safe_and_optional_draft_is_advisory(tmp_path):
    store = setup_store(tmp_path, draft=True)
    service = MechanicVerificationService(store)
    review = service.review("1", "1:42")
    assert review["fight_occurrence_counts"] == {"fight-1": 3}
    assert review["proposed_unverified"]["status"] == "PROPOSED / UNVERIFIED"
    assert "player" not in json.dumps(review).lower()
    assert "report" not in json.dumps(review).lower()
    service.promote("1", "1:42", data())
    promoted = store.load_verified_registry().rules[0]
    assert promoted.definition.failure_category == "avoidable_damage"
    assert promoted.definition.metadata["verification"]["reviewer"] == "operator"


def test_promotion_requires_explicit_semantics_and_stopped_id(tmp_path):
    service = MechanicVerificationService(setup_store(tmp_path))
    for kw in ({"failure_category": "bad"}, {"severity": "bad"}, {"avoidability": None},
               {"selector_interpretation": "stopped_ability"}):
        with pytest.raises((ValueError, TypeError)):
            service.promote("1", "1:42", data(**kw))


def test_replace_merges_and_rejects_silently_overwriting(tmp_path):
    store = setup_store(tmp_path)
    original = {"schema_version": 1, "registry_version": "1", "definitions": [
        {"definition_version": "1", "encounter": {"encounter_id": "1", "name": "Boss"}, "mechanic_id": "other", "name": "Other", "event_types": ["damage"], "ability_ids": [99], "failure_category": "avoidable_damage"}]}
    store.write_verified("1", original)
    service = MechanicVerificationService(store)
    with pytest.raises(MechanicsStoreError, match="replace=True"):
        service.promote("1", "1:42", data())
    service.promote("1", "1:42", data(definition_version="2"), replace=True)
    assert {r.definition.mechanic_id for r in store.load_verified_registry().rules} == {"other", "blast"}
    promoted = next(r for r in store.load_verified_registry().rules if r.definition.mechanic_id == "blast")
    assert promoted.definition_version == "2"
    assert promoted.definition.metadata["verification"]["promotion_version"] == "2"


def test_rejection_ledger_does_not_mutate_discovery_or_enter_registry(tmp_path):
    store = setup_store(tmp_path)
    before = (tmp_path / "discovered" / "1.json").read_bytes()
    service = MechanicVerificationService(store, clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    record = service.reject("1", "1:42", "reviewer", "not a mechanic")
    assert json.loads(record.read_text())["reviews"][0]["status"] == "rejected"
    assert (tmp_path / "discovered" / "1.json").read_bytes() == before
    assert store.load_verified_registry().rules == ()


def test_outcome_subject_semantics_and_synthetic_selector_are_explicit(tmp_path):
    store = DirectoryMechanicsStore(tmp_path)
    store.write_discovery(EncounterDiscovery("1", "Boss", (DiscoveryProvenance("wcl", "b" * 64, "fight-1"),),
        (CandidateMechanic("name:alpha", "Alpha", (EventType.CAST,)),)))
    service = MechanicVerificationService(store)
    with pytest.raises(ValueError, match="explicit ability_selector_id"):
        service.promote("1", "1:name:alpha", data(failure_category="interrupt"))
    with pytest.raises(ValueError, match="explicit outcome"):
        service.promote("1", "1:name:alpha", data(failure_category="interrupt", ability_selector_id=456))
    service.promote("1", "1:name:alpha", data(failure_category="interrupt", ability_selector_id=456,
                    outcome="failure", subject_actor="target"))
    rule = store.load_verified_registry().rules[0]
    assert rule.definition.ability_ids == ("456",)
    assert rule.definition.metadata["outcome"] == "failure"
    assert rule.definition.metadata["subject_actor"] == "target"


def test_stopped_selector_requires_metadata_field_and_matches_normalized_event(tmp_path):
    store = DirectoryMechanicsStore(tmp_path)
    store.write_discovery(EncounterDiscovery("1", "Boss", (DiscoveryProvenance("wcl", "c" * 64, "fight-1"),),
        (CandidateMechanic(42, "Kick", (EventType.INTERRUPT,)),)))
    service = MechanicVerificationService(store)
    with pytest.raises(ValueError, match="stopped_ability_metadata_field"):
        service.promote("1", "1:42", data(failure_category="interrupt", selector_interpretation="stopped_ability",
            stopped_ability_id=12345))
    service.promote("1", "1:42", data(failure_category="interrupt", selector_interpretation="stopped_ability",
        stopped_ability_id="12345", stopped_ability_metadata_field="stopped_ability_id"))
    registry = store.load_verified_registry()
    matches = registry.match(EncounterIdentity("1", "Boss"), NormalizedEvent(
        100, EventType.INTERRUPT, "interrupt-evidence", metadata={"stopped_ability_id": 12345}))
    assert [match.definition.mechanic_id for match in matches] == ["blast"]
