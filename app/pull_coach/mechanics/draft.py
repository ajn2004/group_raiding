"""Deterministic, non-production mechanic review drafts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from typing import Protocol

from app.pull_coach.identity import canonical_ability_id
from app.pull_coach.mechanics.taxonomy import FailureCategory
from app.pull_coach.models import ActorType, CandidateMechanic, EncounterDiscovery, EventType, Role, Severity
from app.pull_coach.models.discovery import DiscoveryProvenance

DRAFT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProposalProvenance:
    provider: str
    version: str | None = None

    def __post_init__(self):
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("proposal provider must be non-empty")
        if self.version is not None and (not isinstance(self.version, str) or not self.version.strip()):
            raise ValueError("proposal version must be a non-empty string or None")


@dataclass(frozen=True)
class SemanticProposal:
    provenance: ProposalProvenance
    confidence: float
    failure_category: FailureCategory | None = None
    avoidable: bool | None = None
    severity: Severity | None = None
    expected_roles: tuple[Role, ...] = ()
    rationale: str | None = None

    def __post_init__(self):
        if type(self.provenance) is not ProposalProvenance:
            raise ValueError("proposal provenance is required")
        if type(self.confidence) not in (float, int) or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be a finite number between 0 and 1")
        if self.failure_category is not None and type(self.failure_category) is not FailureCategory:
            raise ValueError("invalid failure category")
        if self.avoidable is not None and type(self.avoidable) is not bool:
            raise ValueError("avoidable must be boolean or None")
        if self.severity is not None and type(self.severity) is not Severity:
            raise ValueError("invalid severity")
        if not isinstance(self.expected_roles, tuple) or any(type(role) is not Role for role in self.expected_roles):
            raise ValueError("expected_roles must contain Role values")
        if self.rationale is not None and not isinstance(self.rationale, str):
            raise ValueError("rationale must be a string or None")


class SemanticProposalProvider(Protocol):
    def propose(self, candidate: "DraftMechanic") -> SemanticProposal: ...


@dataclass(frozen=True)
class DraftMechanic:
    candidate_id: str
    mechanic_id: str
    ability_id: int | str
    ability_name: str | None
    event_types: tuple[EventType, ...]
    source_actor_type_counts: tuple[tuple[ActorType, int], ...]
    target_actor_type_counts: tuple[tuple[ActorType, int], ...]
    fight_occurrence_counts: tuple[tuple[str, int], ...]
    damage_total: float | None
    first_timestamp: int | None
    last_timestamp: int | None
    death_window_observations: int
    proposal: SemanticProposal | None = None


@dataclass(frozen=True)
class MechanicDraft:
    encounter_id: str
    encounter_name: str
    discovery_schema_version: int
    provenance: tuple[DiscoveryProvenance, ...]
    candidates: tuple[DraftMechanic, ...]
    schema_version: int = DRAFT_SCHEMA_VERSION
    stage: str = "drafted"


def candidate_id_for(encounter_id: str, ability_id: int | str) -> str:
    """Return the stable discovery candidate address, independent of its display name."""
    return f"{encounter_id}:{canonical_ability_id(ability_id)}"


def _mechanic_id_for(candidate_id: str) -> str:
    token = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16]
    return f"mechanic-{token}"


def _draft_candidate(encounter_id: str, candidate: CandidateMechanic) -> DraftMechanic:
    identity = candidate_id_for(encounter_id, candidate.ability_id)
    mechanic_id = _mechanic_id_for(identity)
    return DraftMechanic(identity, mechanic_id, candidate.ability_id, candidate.ability_name,
                         candidate.event_types, candidate.source_actor_type_counts,
                         candidate.target_actor_type_counts, candidate.fight_occurrence_counts,
                         candidate.damage_total, candidate.first_timestamp,
                         candidate.last_timestamp, candidate.death_window_observations)


def draft_to_dict(draft: MechanicDraft) -> dict:
    def proposal_dict(proposal):
        if proposal is None:
            return None
        return {"provider": proposal.provenance.provider, "provider_version": proposal.provenance.version,
                "confidence": proposal.confidence,
                "failure_category": proposal.failure_category.value if proposal.failure_category else None,
                "avoidable": proposal.avoidable, "severity": proposal.severity.value if proposal.severity else None,
                "expected_roles": [role.value for role in proposal.expected_roles], "rationale": proposal.rationale}

    return {"schema_version": draft.schema_version, "stage": draft.stage,
            "encounter": {"id": draft.encounter_id, "name": draft.encounter_name},
            "source_discovery_schema_version": draft.discovery_schema_version,
            "provenance": [{"provider": p.provider, "source_fingerprint": p.source_fingerprint,
                            "fight_id": p.fight_id} for p in draft.provenance],
            "candidates": [{"candidate_id": c.candidate_id, "mechanic_id": c.mechanic_id,
                            "ability_id": c.ability_id, "ability_name": c.ability_name,
                            "event_types": [x.value for x in c.event_types],
                            "ability_ids": ([] if isinstance(c.ability_id, str) and c.ability_id.startswith("name:")
                                             else [c.ability_id]),
                            "stopped_ability_ids": [],
                            "source_actor_type_counts": [[x.value, n] for x, n in c.source_actor_type_counts],
                            "target_actor_type_counts": [[x.value, n] for x, n in c.target_actor_type_counts],
                            "fight_occurrence_counts": [list(x) for x in c.fight_occurrence_counts],
                            "damage_total": c.damage_total, "first_timestamp": c.first_timestamp,
                            "last_timestamp": c.last_timestamp,
                            "death_window_observations": c.death_window_observations,
                            "semantics": {"failure_category": None, "avoidable": None, "severity": None,
                                          "expected_roles": None, "exposure": None,
                                          "target_priority": None, "timing": None,
                                          "metadata_predicates": None, "causal_explanation": None},
                            "proposal": proposal_dict(c.proposal)} for c in draft.candidates]}


def draft_to_json(draft: MechanicDraft) -> str:
    return json.dumps(draft_to_dict(draft), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class MechanicDraftService:
    def __init__(self, store=None):
        self.store = store

    def generate(self, discovery: EncounterDiscovery, proposal_provider: SemanticProposalProvider | None = None) -> MechanicDraft:
        candidates = []
        for observed in discovery.candidates:
            factual = _draft_candidate(discovery.encounter_id, observed)
            proposal = None
            if proposal_provider is not None:
                try:
                    proposed = proposal_provider.propose(factual)
                    if type(proposed) is SemanticProposal:
                        proposal = proposed
                except Exception:
                    # A proposal outage cannot block deterministic factual drafting.
                    proposal = None
            candidates.append(DraftMechanic(**{**factual.__dict__, "proposal": proposal}))
        return MechanicDraft(discovery.encounter_id, discovery.encounter_name,
                             discovery.schema_version, discovery.provenance, tuple(candidates))

    def generate_from_store(self, encounter_id: str, proposal_provider: SemanticProposalProvider | None = None) -> MechanicDraft:
        if self.store is None:
            raise ValueError("a mechanics store is required")
        discovery = self.store.read_discovery(encounter_id)
        if discovery is None:
            raise ValueError(f"no discovery artifact for encounter {encounter_id!r}")
        return self.generate(discovery, proposal_provider)

    def write(self, draft: MechanicDraft):
        if self.store is None:
            raise ValueError("a mechanics store is required")
        return self.store.write_draft(draft.encounter_id, draft_to_dict(draft))

    def generate_and_write(self, encounter_id: str, proposal_provider: SemanticProposalProvider | None = None):
        draft = self.generate_from_store(encounter_id, proposal_provider)
        self.write(draft)
        return draft
