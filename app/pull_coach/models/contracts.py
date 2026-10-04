"""Provider- and presentation-independent Pull Coach value objects."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class PullState(str, Enum):
    KILL = "kill"
    WIPE = "wipe"
    IN_PROGRESS = "in_progress"


class Role(str, Enum):
    TANK = "tank"
    HEALER = "healer"
    DAMAGE = "damage"
    UNKNOWN = "unknown"


class EventType(str, Enum):
    DAMAGE = "damage"
    HEAL = "heal"
    CAST = "cast"
    DEATH = "death"
    INTERRUPT = "interrupt"
    DISPEL = "dispel"
    RESOURCE = "resource"
    OTHER = "other"


class ExposureState(str, Enum):
    EXPOSED = "exposed"
    NOT_EXPOSED = "not_exposed"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingCategory(str, Enum):
    MECHANIC = "mechanic"
    DEATH = "death"
    INTERRUPT = "interrupt"
    DISPEL = "dispel"
    OTHER = "other"


class ProgressionStatus(str, Enum):
    IMPROVED = "improved"
    STABLE = "stable"
    REGRESSED = "regressed"
    NEWLY_OBSERVED = "newly_observed"
    RESOLVED = "resolved"
    STABILIZED = "stabilized"


@dataclass(frozen=True)
class SourceIdentity:
    provider: str
    source_id: str


@dataclass(frozen=True)
class RaidReportIdentity:
    source: SourceIdentity
    report_code: str


@dataclass(frozen=True)
class EncounterIdentity:
    encounter_id: str
    name: str


@dataclass(frozen=True)
class PullIdentity:
    report: RaidReportIdentity
    encounter: EncounterIdentity
    fight_id: str
    pull_number: int
    start_timestamp: int
    end_timestamp: int | None
    state: PullState
    boss_percent: float | None = None

    def __post_init__(self) -> None:
        if self.pull_number < 1:
            raise ValueError("pull_number must be >= 1")
        if self.end_timestamp is not None and self.end_timestamp < self.start_timestamp:
            raise ValueError("end_timestamp must not precede start_timestamp")


@dataclass(frozen=True)
class Actor:
    actor_id: str
    name: str
    player_name: str | None = None
    class_name: str | None = None
    spec_name: str | None = None
    role: Role | None = None
    source: SourceIdentity | None = None


@dataclass(frozen=True)
class NormalizedEvent:
    timestamp: int
    event_type: EventType
    evidence_id: str
    source_actor_id: str | None = None
    target_actor_id: str | None = None
    ability_id: int | str | None = None
    ability_name: str | None = None
    amount: float | None = None
    absorbed: float | None = None
    overkill: float | None = None
    flags: frozenset[str] = frozenset()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("normalized events require a non-empty evidence_id")


def normalized_event(**kwargs: Any) -> NormalizedEvent:
    """Convenience constructor kept as a named boundary for future normalizers."""
    return NormalizedEvent(**kwargs)


@dataclass(frozen=True)
class TimingWindow:
    start_offset_ms: int
    end_offset_ms: int


@dataclass(frozen=True)
class MechanicDefinition:
    mechanic_id: str
    encounter: EncounterIdentity
    name: str
    failure_category: str
    ability_ids: tuple[int | str, ...] = ()
    avoidable: bool | None = None
    expected_roles: tuple[Role, ...] = ()
    severity: Severity = Severity.MEDIUM
    timing_window: TimingWindow | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MechanicExposure:
    mechanic_id: str
    state: ExposureState
    opportunity_count: int | None = None
    evidence: tuple["EvidenceReference", ...] = ()

    def __post_init__(self) -> None:
        if self.opportunity_count is not None and self.opportunity_count < 0:
            raise ValueError("opportunity_count must be non-negative")


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: str
    event_ids: tuple[str, ...] = ()
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() and not self.event_ids:
            raise ValueError("an evidence reference must identify an evidence or event ID")


@dataclass(frozen=True)
class MechanicObservation:
    observation_id: str
    mechanic_id: str
    timestamp: int
    actor_ids: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence or not all(isinstance(item, EvidenceReference) for item in self.evidence):
            raise ValueError("a mechanic observation must include evidence references")


@dataclass(frozen=True)
class Finding:
    finding_id: str
    category: FindingCategory
    severity: Severity
    fact: Mapping[str, Any]
    evidence: tuple[EvidenceReference, ...]
    actor_ids: tuple[str, ...] = ()
    roles: tuple[Role, ...] = ()
    mechanic_id: str | None = None
    related_finding_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence or not all(isinstance(item, EvidenceReference) for item in self.evidence):
            raise ValueError("a finding must include evidence references")


@dataclass(frozen=True)
class SummaryMetrics:
    values: Mapping[str, float | int | str] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisMetadata:
    analyzer_name: str
    analyzer_version: str


@dataclass(frozen=True)
class PullAnalysis:
    pull: PullIdentity
    findings: tuple[Finding, ...]
    mechanic_observations: tuple[MechanicObservation, ...]
    summary: SummaryMetrics
    analyzer: AnalysisMetadata
    mechanic_exposures: tuple[MechanicExposure, ...] = ()


@dataclass(frozen=True)
class ProgressionDelta:
    subject_id: str
    status: ProgressionStatus
    previous_pull_number: int | None
    current_pull_number: int
    metric: str | None = None
    previous_value: float | None = None
    current_value: float | None = None
