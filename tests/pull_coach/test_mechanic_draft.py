import json

import pytest

from app.pull_coach.mechanics.draft import (
    MechanicDraftService, ProposalProvenance, SemanticProposal, candidate_id_for, draft_to_json,
)
from app.pull_coach.mechanics.loader import MechanicSchemaError, load_mechanic_registry
from app.pull_coach.mechanics.store import DirectoryMechanicsStore
from app.pull_coach.mechanics.taxonomy import FailureCategory
from app.pull_coach.models import ActorType, CandidateMechanic, EncounterDiscovery, EventType, Role, Severity
from app.pull_coach.models.discovery import DiscoveryProvenance


def discovery(ability_id= "00999", name="Display Name"):
    return EncounterDiscovery("10", "Encounter", (DiscoveryProvenance("wcl", "a" * 64, "1"),),
        (CandidateMechanic(ability_id, name, (EventType.INTERRUPT,),
          ((ActorType.NPC, 2),), ((ActorType.PLAYER, 1),), (("1", 2),), None, 10, 20, 1),))


def test_draft_is_deterministic_factual_and_keeps_semantics_unresolved(tmp_path):
    observed = discovery()
    service = MechanicDraftService()
    draft = service.generate(observed)
    encoded = draft_to_json(draft)
    assert encoded == draft_to_json(service.generate(observed))
    artifact = json.loads(encoded)
    candidate = artifact["candidates"][0]
    assert candidate["candidate_id"] == "10:999"
    assert candidate["mechanic_id"] == service.generate(discovery(name="Renamed")).candidates[0].mechanic_id
    assert candidate["ability_ids"] == ["999"]
    assert candidate["event_types"] == ["interrupt"]
    assert candidate["stopped_ability_ids"] == []
    assert all(value is None for value in candidate["semantics"].values())
    assert candidate["proposal"] is None
    assert "Display Name" in encoded and "player" in encoded
    assert all(secret not in encoded for secret in ("private-code", "Player Name", "actor_id"))

    store = DirectoryMechanicsStore(tmp_path)
    service = MechanicDraftService(store)
    store.write_discovery(observed)
    service.generate_and_write("10")
    assert store.read_draft("10") == json.loads(encoded)
    path = tmp_path / "drafts" / "10.json"
    with pytest.raises(MechanicSchemaError):
        load_mechanic_registry(path)


def test_provider_success_is_separate_and_validated():
    class Provider:
        def propose(self, candidate):
            assert candidate.ability_id == "999"
            return SemanticProposal(ProposalProvenance("fake", "v1"), 0.75,
                                    FailureCategory.INTERRUPT, True, Severity.HIGH, (Role.DAMAGE,), "review me")

    candidate = MechanicDraftService().generate(discovery(), Provider()).candidates[0]
    assert candidate.ability_id == "999"
    assert candidate.proposal.failure_category is FailureCategory.INTERRUPT
    result = json.loads(draft_to_json(MechanicDraftService().generate(discovery(), Provider())))
    assert result["candidates"][0]["semantics"]["failure_category"] is None
    assert result["candidates"][0]["proposal"]["provider"] == "fake"


def test_provider_failure_or_invalid_output_does_not_block_factual_scaffold():
    class Outage:
        def propose(self, candidate):
            raise TimeoutError("offline")

    class Invalid:
        def propose(self, candidate):
            return {"failure_category": "made_up", "confidence": 2}

    service = MechanicDraftService()
    baseline = draft_to_json(service.generate(discovery()))
    assert draft_to_json(service.generate(discovery(), Outage())) == baseline
    assert draft_to_json(service.generate(discovery(), Invalid())) == baseline
    with pytest.raises(ValueError):
        SemanticProposal(ProposalProvenance("fake"), float("nan"))
    with pytest.raises(ValueError):
        SemanticProposal(ProposalProvenance("fake"), 0.5, failure_category="made_up")


def test_numeric_ability_ids_are_canonical_and_identity_ignores_name():
    first = MechanicDraftService().generate(discovery(999, "One")).candidates[0]
    second = MechanicDraftService().generate(discovery("000999", "Two")).candidates[0]
    assert first.ability_id == second.ability_id == "999"
    assert first.candidate_id == second.candidate_id == "10:999"
    assert first.mechanic_id == second.mechanic_id


def test_name_only_identity_is_preserved_but_not_projected_as_ability_selector():
    candidate = MechanicDraftService().generate(discovery("name:alpha", "Alpha" )).candidates[0]
    data = json.loads(draft_to_json(MechanicDraftService().generate(discovery("name:alpha", "Alpha"))))
    assert candidate.candidate_id == candidate_id_for("10", "name:alpha") == "10:name:alpha"
    assert data["candidates"][0]["candidate_id"] == "10:name:alpha"
    assert data["candidates"][0]["ability_id"] == "name:alpha"
    assert data["candidates"][0]["ability_ids"] == []
