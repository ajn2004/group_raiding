"""Stable knobs for deterministic single-pull analysis."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalyzerConfig:
    """Defaults: inspect 5 seconds before death; 2 hits count as repeated;
    group raid-damage events separated by at most 1 second into one window.
    """

    pre_death_window_ms: int = 5000
    repeated_failure_threshold: int = 2
    raid_window_gap_ms: int = 1000

    def __post_init__(self) -> None:
        if self.pre_death_window_ms < 0 or self.raid_window_gap_ms < 0:
            raise ValueError("analysis timing windows must be non-negative")
        if self.repeated_failure_threshold < 1:
            raise ValueError("repeated_failure_threshold must be >= 1")
