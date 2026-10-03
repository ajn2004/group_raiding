"""Data-driven encounter mechanic recognition."""

from app.pull_coach.mechanics.loader import (
    MechanicSchemaError, UnsupportedMechanicSchemaVersion,
    definitions_from_dict, load_mechanic_definitions, load_mechanic_registry, registry_from_dict,
)
from app.pull_coach.mechanics.registry import MechanicMatch, MechanicRegistry, MechanicRule
from app.pull_coach.mechanics.taxonomy import FailureCategory

__all__ = [
    "FailureCategory", "MechanicMatch", "MechanicRegistry", "MechanicRule",
    "MechanicSchemaError", "UnsupportedMechanicSchemaVersion",
    "definitions_from_dict", "load_mechanic_definitions", "load_mechanic_registry", "registry_from_dict",
]
