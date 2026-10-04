"""Stable classifications used to describe mechanic semantics."""

from enum import Enum


class FailureCategory(str, Enum):
    AVOIDABLE_DAMAGE = "avoidable_damage"
    UNAVOIDABLE_DAMAGE = "unavoidable_damage"
    HEALING_CHECK = "healing_check"
    POSITIONING = "positioning"
    INTERRUPT = "interrupt"
    DISPEL = "dispel"
    TARGET_PRIORITY = "target_priority"
    TANK_EXECUTION = "tank_execution"
    COOLDOWN_OR_RESOURCE = "cooldown_or_resource"
    ASSIGNMENT = "assignment"
