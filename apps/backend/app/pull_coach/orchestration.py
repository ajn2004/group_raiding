"""Source-agnostic selection boundary for live Pull Coach runs.

Provider adapters return structured coaching results. This module owns only the
selection and fallback policy; provider-specific payloads stay behind adapters.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class CoachingSourceError(Exception):
    """A configured coaching source failed to produce a result."""


class SourceMode(str, Enum):
    WIPEFEST_PRIMARY = "wipefest"
    LEGACY_ONLY = "legacy"


class CoachingSource(Protocol):
    def coach(self, report_reference: str, fight: dict[str, Any]) -> "CoachingRunResult": ...
    def coach_player(self, report_reference: str, fight: dict[str, Any], character: str) -> "CoachingRunResult": ...


@dataclass(frozen=True)
class CoachingRunResult:
    report_code: str
    fight_id: str
    encounter_id: str
    encounter_name: str
    source_url: str
    coaching: dict[str, Any]
    session_id: int | None
    source: str
    legacy_result: object | None = None


@dataclass(frozen=True)
class SourceSelection:
    mode: SourceMode = SourceMode.WIPEFEST_PRIMARY
    legacy_fallback: bool = False

    def __post_init__(self):
        if self.mode is SourceMode.LEGACY_ONLY and self.legacy_fallback:
            raise ValueError("legacy fallback is meaningless in legacy-only mode")


class CoachingOrchestrator:
    """Run the configured primary source and apply explicit fallback policy."""

    def __init__(self, wipefest: CoachingSource, legacy: CoachingSource,
                 selection: SourceSelection = SourceSelection()):
        self.wipefest = wipefest
        self.legacy = legacy
        self.selection = selection

    def coach(self, report_reference: str, fight: dict[str, Any]) -> CoachingRunResult:
        if self.selection.mode is SourceMode.LEGACY_ONLY:
            return self.legacy.coach(report_reference, fight)
        try:
            return self.wipefest.coach(report_reference, fight)
        except CoachingSourceError:
            if not self.selection.legacy_fallback:
                raise
        return self.legacy.coach(report_reference, fight)

    def coach_player(self, report_reference: str, fight: dict[str, Any], character: str) -> CoachingRunResult:
        if self.selection.mode is SourceMode.LEGACY_ONLY:
            raise CoachingSourceError("individual Wipefest coaching is unavailable in legacy mode")
        method = getattr(self.wipefest, "coach_player", None)
        if method is None:
            raise CoachingSourceError("individual coaching is not configured")
        return method(report_reference, fight, character)
