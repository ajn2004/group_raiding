"""Immutable structured output for DAL-48 progression comparisons."""
from dataclasses import dataclass

from app.pull_coach.models import ProgressionDelta, ProgressionStatus, PullIdentity


@dataclass(frozen=True)
class ProgressionSubject:
    subject_id: str
    subject_type: str
    status: ProgressionStatus
    occurrence_count: int
    max_severity_rank: int
    mechanic_id: str | None = None
    failure_category: str | None = None
    actor_id: str | None = None
    role: str | None = None
    repeated: bool = False
    death_linked: bool = False
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BlockerPriority:
    severity_rank: int
    repeated: bool
    occurrence_count: int
    death_linked: bool


@dataclass(frozen=True)
class ProgressionBlocker:
    subject: ProgressionSubject
    priority: BlockerPriority


@dataclass(frozen=True)
class ProgressionComparison:
    comparator_name: str
    comparator_version: str
    encounter_id: str
    current_pull: PullIdentity
    compared_pull_numbers: tuple[int, ...]
    pull_result: ProgressionStatus | None
    deltas: tuple[ProgressionDelta, ...]
    subjects: tuple[ProgressionSubject, ...]
    newly_exposed_blocker: ProgressionBlocker | None
