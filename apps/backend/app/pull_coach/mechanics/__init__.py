"""Data-driven encounter mechanic recognition."""

from app.pull_coach.mechanics.loader import (
    MechanicSchemaError, UnsupportedMechanicSchemaVersion,
    definitions_from_dict, load_mechanic_definitions, load_mechanic_registry, registry_from_dict,
)
from app.pull_coach.mechanics.registry import MechanicMatch, MechanicRegistry, MechanicRule
from app.pull_coach.mechanics.taxonomy import FailureCategory
from app.pull_coach.mechanics.draft import (
    DRAFT_SCHEMA_VERSION, DraftMechanic, MechanicDraft, MechanicDraftService,
    ProposalProvenance, SemanticProposal, SemanticProposalProvider,
    candidate_id_for, draft_to_dict, draft_to_json,
)

__all__ = [
    "FailureCategory", "MechanicMatch", "MechanicRegistry", "MechanicRule",
    "DRAFT_SCHEMA_VERSION", "DraftMechanic", "MechanicDraft", "MechanicDraftService",
    "ProposalProvenance", "SemanticProposal", "SemanticProposalProvider",
    "candidate_id_for", "draft_to_dict", "draft_to_json",
    "MechanicSchemaError", "UnsupportedMechanicSchemaVersion",
    "definitions_from_dict", "load_mechanic_definitions", "load_mechanic_registry", "registry_from_dict",
]
