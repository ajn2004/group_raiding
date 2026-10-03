"""Explicit thresholds for deterministic pull progression comparisons."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressionConfig:
    # Boss health remaining and failure counts are lower-is-better.
    boss_percent_threshold: float = 1.0
    duration_threshold_ms: int = 5000
    first_death_threshold_ms: int = 5000
    mechanic_count_threshold: int = 1
    severity_rank_threshold: int = 1
    stabilization_pulls: int = 2

    def __post_init__(self):
        if self.boss_percent_threshold < 0 or self.duration_threshold_ms < 0 or self.first_death_threshold_ms < 0:
            raise ValueError("progression thresholds must be non-negative")
        if self.mechanic_count_threshold < 1 or self.severity_rank_threshold < 1 or self.stabilization_pulls < 1:
            raise ValueError("count and stabilization thresholds must be >= 1")
