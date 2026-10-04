"""Human-controlled promotion of observed mechanics into the verified registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable

from app.pull_coach.mechanics.loader import definitions_from_dict
from app.pull_coach.mechanics.draft import candidate_id_for
from app.pull_coach.mechanics.store import DirectoryMechanicsStore, MechanicsStoreError
from app.pull_coach.mechanics.taxonomy import FailureCategory
from app.pull_coach.identity import canonical_ability_id
from app.pull_coach.models import EventType, Role, Severity, discovery_to_json


@dataclass(frozen=True)
class VerifiedMechanicInput:
    """All semantics used for promotion are supplied deliberately by a reviewer."""

    mechanic_id: str
    name: str
    failure_category: str
    severity: str
    avoidability: str  # true / false / unknown
    expected_roles: tuple[str, ...]
    selector_interpretation: str  # observed_ability or stopped_ability
    reviewer: str
    ability_selector_id: int | str | None = None
    outcome: str | None = None
    subject_actor: str | None = None
    definition_version: str | None = None
    timing_window: dict | None = None
    stopped_ability_id: int | str | None = None
    stopped_ability_metadata_field: str | None = None
    metadata_predicates: dict | None = None
    exposure: dict | None = None
    weight: float = 1.0


class MechanicVerificationService:
    def __init__(self, store: DirectoryMechanicsStore, *, clock: Callable[[], datetime] | None = None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def review(self, encounter_id: str, candidate_id: str) -> dict:
        discovery = self.store.read_discovery(encounter_id)
        if discovery is None:
            raise MechanicsStoreError(f"no discovery artifact for encounter {encounter_id!r}")
        candidate = next((c for c in discovery.candidates
                          if candidate_id in (str(c.ability_id), candidate_id_for(encounter_id, c.ability_id))), None)
        if candidate is None:
            raise MechanicsStoreError(f"candidate {candidate_id!r} not found for encounter {encounter_id!r}")
        fingerprints = sorted({p.source_fingerprint for p in discovery.provenance})
        fights = sorted({p.fight_id for p in discovery.provenance})
        result = {
            "encounter_id": discovery.encounter_id, "encounter_name": discovery.encounter_name,
            "candidate_id": candidate_id_for(encounter_id, candidate.ability_id), "ability_id": candidate.ability_id,
            "ability_name": candidate.ability_name, "event_types": [x.value for x in candidate.event_types],
            "source_actor_type_counts": {x.value: n for x, n in candidate.source_actor_type_counts},
            "target_actor_type_counts": {x.value: n for x, n in candidate.target_actor_type_counts},
            "fight_occurrence_counts": dict(candidate.fight_occurrence_counts),
            "damage_total": candidate.damage_total, "first_timestamp": candidate.first_timestamp,
            "last_timestamp": candidate.last_timestamp,
            "death_window_association_count": candidate.death_window_observations,
            "source_fingerprints": fingerprints, "fight_ids": fights,
            "discovery_schema_version": discovery.schema_version,
        }
        draft = self.store.read_draft(encounter_id)
        proposals = _proposals(draft, candidate_id_for(encounter_id, candidate.ability_id)) if draft else None
        if proposals is not None:
            result["proposed_unverified"] = proposals
        return result

    def promote(self, encounter_id: str, candidate_id: str, verified: VerifiedMechanicInput, *, replace: bool = False) -> Path:
        facts = self.review(encounter_id, candidate_id)
        discovery = self.store.read_discovery(encounter_id)
        candidate = next(c for c in discovery.candidates
                         if candidate_id in (str(c.ability_id), candidate_id_for(encounter_id, c.ability_id)))
        if not isinstance(verified, VerifiedMechanicInput):
            raise TypeError("verified must be a VerifiedMechanicInput")
        if not verified.mechanic_id or not verified.name or not verified.reviewer:
            raise ValueError("mechanic_id, name, and reviewer are required")
        category = FailureCategory(verified.failure_category).value
        severity = Severity(verified.severity).value
        if verified.avoidability not in ("true", "false", "unknown"):
            raise ValueError("avoidability must explicitly be true, false, or unknown")
        roles = [Role(role).value for role in verified.expected_roles]
        if len(roles) != len(set(roles)):
            raise ValueError("expected_roles must not contain duplicates")
        if verified.selector_interpretation not in ("observed_ability", "stopped_ability"):
            raise ValueError("selector_interpretation must be observed_ability or stopped_ability")
        if verified.selector_interpretation == "stopped_ability":
            if verified.stopped_ability_id is None:
                raise ValueError("stopped_ability_id must be explicitly supplied for stopped_ability selector")
            if not verified.stopped_ability_metadata_field or not verified.stopped_ability_metadata_field.strip():
                raise ValueError("stopped_ability_metadata_field must be explicitly supplied for stopped_ability selector")
        if verified.selector_interpretation == "observed_ability" and verified.stopped_ability_id is not None:
            raise ValueError("stopped_ability_id requires stopped_ability selector interpretation")
        synthetic = isinstance(candidate.ability_id, str) and candidate.ability_id.startswith("name:")
        selector_id = verified.ability_selector_id
        if synthetic and selector_id is None and verified.selector_interpretation == "observed_ability":
            raise ValueError("synthetic name candidate requires explicit ability_selector_id for observed_ability")
        if verified.selector_interpretation == "observed_ability":
            selector_id = candidate.ability_id if selector_id is None else selector_id
            selector_id = canonical_ability_id(selector_id)
            if selector_id.startswith("name:"):
                raise ValueError("ability_selector_id must be a real ability selector, not a synthetic name identity")
        if verified.outcome not in (None, "failure", "success"):
            raise ValueError("outcome must be failure, success, or explicitly omitted")
        if (EventType.CAST in candidate.event_types and category in ("interrupt", "dispel")
                and verified.outcome is None):
            raise ValueError("cast-based interrupt/dispel mechanics require an explicit outcome")
        if verified.subject_actor not in (None, "source", "target"):
            raise ValueError("subject_actor must be source, target, or explicitly omitted")
        if verified.definition_version is not None and (not isinstance(verified.definition_version, str) or not verified.definition_version.strip()):
            raise ValueError("definition_version must be a non-empty string")
        mechanic_path = self.store.root / "verified" / f"{encounter_id}.json"
        previous = None
        if mechanic_path.exists():
            existing_document = json.loads(mechanic_path.read_text(encoding="utf-8"))
            previous = next((d for d in existing_document.get("definitions", []) if d.get("mechanic_id") == verified.mechanic_id), None)
        if replace and previous is not None and verified.definition_version is None:
            raise ValueError("definition_version is required when updating an existing mechanic")
        if previous is not None and verified.definition_version == previous.get("definition_version", "1"):
            raise ValueError("definition_version must change when replacing an existing mechanic")
        definition_version = verified.definition_version or "1"
        now = self.clock()
        provenance = {
            "source_encounter_id": encounter_id, "source_candidate_id": candidate_id_for(encounter_id, candidate.ability_id),
            "source_discovery_schema_version": discovery.schema_version,
            "source_fingerprints": facts["source_fingerprints"], "source_fight_ids": facts["fight_ids"],
            "source_discovery_sha256": hashlib.sha256(discovery_to_json(discovery).encode()).hexdigest(),
            "reviewer": verified.reviewer, "verified_at": now.isoformat(), "promotion_version": definition_version,
        }
        definition = {
            "definition_version": definition_version, "encounter": {"encounter_id": encounter_id, "name": discovery.encounter_name},
            "mechanic_id": verified.mechanic_id, "name": verified.name,
            "event_types": [event.value for event in candidate.event_types],
            "failure_category": category, "severity": severity,
            "avoidable": {"true": True, "false": False, "unknown": None}[verified.avoidability],
            "expected_roles": roles, "weight": verified.weight,
            "timing_window": verified.timing_window, "metadata_predicates": verified.metadata_predicates or {},
            "metadata": {"verification": provenance},
        }
        if verified.outcome is not None:
            definition["metadata"]["outcome"] = verified.outcome
        if verified.subject_actor is not None:
            definition["metadata"]["subject_actor"] = verified.subject_actor
        if verified.selector_interpretation == "observed_ability":
            definition["ability_ids"] = [selector_id]
        else:
            definition["stopped_ability_ids"] = [verified.stopped_ability_id]
            if verified.stopped_ability_metadata_field:
                definition["stopped_ability_metadata_field"] = verified.stopped_ability_metadata_field
        if verified.exposure is not None:
            definition["exposure"] = verified.exposure
        document = {"schema_version": 1, "registry_version": "1", "definitions": [definition]}
        # Validate the canonical production definition before considering activation.
        definitions_from_dict(document)
        path = self.store.root / "verified" / f"{encounter_id}.json"
        if path.exists():
            if not replace:
                raise MechanicsStoreError(f"verified mechanics file already exists: {path}; pass replace=True to update it")
            existing = json.loads(path.read_text(encoding="utf-8"))
            definitions = existing["definitions"]
            definitions = [d for d in definitions if d.get("mechanic_id") != verified.mechanic_id]
            definitions.append(definition)
            document = {**existing, "definitions": definitions}
        return self.store.write_verified(encounter_id, document, replace=replace)

    def reject(self, encounter_id: str, candidate_id: str, reviewer: str, reason: str | None = None) -> Path:
        self.review(encounter_id, candidate_id)  # Validate identity without changing discovery.
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        record = {"encounter_id": encounter_id, "candidate_id": self.review(encounter_id, candidate_id)["candidate_id"], "reviewer": reviewer,
                  "reviewed_at": self.clock().isoformat(), "status": "rejected", "reason": reason}
        path = self.store.root / "reviews" / f"{encounter_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        prior = json.loads(path.read_text()) if path.exists() else {"reviews": []}
        prior.setdefault("reviews", []).append(record)
        return DirectoryMechanicsStore._atomic_write(path, json.dumps(prior, sort_keys=True, separators=(",", ":")) + "\n")


def _proposals(draft: dict, candidate_id: str):
    # DAL-63 wire contract: candidates[].candidate_id and candidates[].proposal.
    values = draft.get("candidates", [])
    if not isinstance(values, list):
        return None
    item = next((value for value in values if isinstance(value, dict) and value.get("candidate_id") == candidate_id), None)
    if item is not None:
        proposal = item.get("proposal")
        return {"status": "PROPOSED / UNVERIFIED", "proposal": proposal} if proposal is not None else None
    # Accept earlier experimental proposal layouts without making them authoritative.
    values = draft.get("proposals", draft.get("definitions", []))
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, list):
        return None
    return next(({"status": "PROPOSED / UNVERIFIED", **value} for value in values
                 if isinstance(value, dict) and str(value.get("ability_id", value.get("ability_ids", [None])[0] if value.get("ability_ids") else "")) == candidate_id), None)
