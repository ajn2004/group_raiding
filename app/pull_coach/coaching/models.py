"""Provider-independent, immutable coaching values."""
from dataclasses import dataclass
from typing import Any

from app.pull_coach.progression.models import ProgressionComparison


@dataclass(frozen=True)
class GroundedFinding:
    finding_id: str
    pull_number: int
    category: str
    severity: str
    mechanic_id: str | None
    mechanic_label: str | None
    failure_category: str | None
    fact: tuple[tuple[str, Any], ...]
    evidence_ids: tuple[str, ...]
    actor_ids: tuple[str, ...]
    roles: tuple[str, ...]


@dataclass(frozen=True)
class CoachingInput:
    fight_id: str
    encounter_id: str
    pull_number: int
    findings: tuple[GroundedFinding, ...]
    progression: ProgressionComparison
    mechanic_labels: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CoachingCandidate:
    candidate_id: str
    audience: str
    kind: str
    finding_ids: tuple[str, ...]
    progression_subject_ids: tuple[str, ...]
    mechanic_id: str | None
    failure_category: str | None
    severity: str
    text: str


@dataclass(frozen=True)
class CoachingSelection:
    primary_failure_id: str | None = None
    improvement_ids: tuple[str, ...] = ()
    dps_action_ids: tuple[str, ...] = ()
    healer_action_ids: tuple[str, ...] = ()
    tank_action_ids: tuple[str, ...] = ()
    raid_action_ids: tuple[str, ...] = ()
    priority_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicCoaching:
    primary_failure: CoachingCandidate | None
    improvements: tuple[CoachingCandidate, ...]
    dps_actions: tuple[CoachingCandidate, ...]
    healer_actions: tuple[CoachingCandidate, ...]
    tank_actions: tuple[CoachingCandidate, ...]
    raid_actions: tuple[CoachingCandidate, ...]
    next_pull_priorities: tuple[CoachingCandidate, ...]


@dataclass(frozen=True)
class PrivatePlayerFeedback:
    actor_id: str
    finding_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeneratorMetadata:
    generator: str
    model: str | None
    template_version: str
    status: str


@dataclass(frozen=True)
class ValidationMetadata:
    rejected_ids: tuple[str, ...] = ()
    used_fallback: bool = False


@dataclass(frozen=True)
class CoachingResult:
    input: CoachingInput
    candidates: tuple[CoachingCandidate, ...]
    public: PublicCoaching
    private_feedback: tuple[PrivatePlayerFeedback, ...]
    rendered_text: str
    metadata: GeneratorMetadata
    validation: ValidationMetadata
