"""Strict standard-library JSON loader for versioned mechanic definitions."""

import json
from pathlib import Path
from typing import Any

from app.pull_coach.mechanics.registry import MechanicRegistry, MechanicRule
from app.pull_coach.mechanics.taxonomy import FailureCategory
from app.pull_coach.models import (
    EncounterIdentity, EventType, MechanicDefinition, Role, Severity, TimingWindow,
)

SCHEMA_VERSION = 1


class MechanicSchemaError(ValueError):
    """A mechanic document is malformed or internally ambiguous."""


class UnsupportedMechanicSchemaVersion(MechanicSchemaError):
    """No loader is available for the requested mechanic schema version."""


def definitions_from_dict(data: dict[str, Any]) -> tuple[MechanicRule, ...]:
    if not isinstance(data, dict):
        raise MechanicSchemaError("mechanic document must be a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedMechanicSchemaVersion(
            f"schema_version {version!r} is unsupported; expected {SCHEMA_VERSION}"
        )
    registry_version = data.get("registry_version", str(version))
    definitions = data.get("definitions")
    if not isinstance(registry_version, str) or not registry_version:
        raise MechanicSchemaError("registry_version must be a non-empty string")
    if not isinstance(definitions, list):
        raise MechanicSchemaError("definitions must be an array")
    rules = []
    try:
        for item in definitions:
            encounter = EncounterIdentity(**item["encounter"])
            ability_ids = tuple(item.get("ability_ids", ()))
            stopped_ids = tuple(item.get("stopped_ability_ids", ()))
            event_types = tuple(sorted({EventType(value) for value in item["event_types"]}, key=lambda value: value.value))
            timing = TimingWindow(**item["timing_window"]) if item.get("timing_window") else None
            definition = MechanicDefinition(
                mechanic_id=item["mechanic_id"], encounter=encounter, name=item["name"],
                failure_category=FailureCategory(item["failure_category"]).value,
                ability_ids=ability_ids,
                avoidable=item.get("avoidable"),
                expected_roles=tuple(Role(value) for value in item.get("expected_roles", ())),
                severity=Severity(item.get("severity", "medium")), timing_window=timing,
                metadata=item.get("metadata", {}),
            )
            if not definition.mechanic_id or not definition.name or not event_types:
                raise ValueError("mechanic_id, name, and event_types must be non-empty")
            if definition.avoidable not in (True, False, None):
                raise ValueError("avoidable must be true, false, or null")
            if not ability_ids and not stopped_ids:
                raise ValueError("each mechanic rule requires ability_ids or stopped_ability_ids")
            weight = item.get("weight", 1.0)
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise ValueError("weight must be numeric")
            rules.append(MechanicRule(
                definition=definition,
                definition_version=str(item.get("definition_version", "1")),
                event_types=event_types,
                weight=float(weight),
                metadata_predicates=_object_field(item, "metadata_predicates"),
                stopped_ability_ids=stopped_ids,
                stopped_ability_metadata_field=item.get("stopped_ability_metadata_field"),
                relationships=_object_field(item, "relationships"),
            ))
            for key, value in (rules[-1].metadata_predicates or {}).items():
                if value is not None and not isinstance(value, (str, int, float, bool)):
                    raise ValueError(f"metadata_predicates[{key!r}] must be a JSON scalar")
    except (KeyError, TypeError, ValueError) as exc:
        raise MechanicSchemaError(f"invalid mechanic definition: {exc}") from exc
    identities = [(r.definition.encounter.encounter_id, r.definition.mechanic_id) for r in rules]
    if len(identities) != len(set(identities)):
        raise MechanicSchemaError("duplicate mechanic_id for encounter")
    # Validate selector ambiguity at load time, producing a configuration error.
    try:
        MechanicRegistry(tuple(rules), registry_version)
    except ValueError as exc:
        raise MechanicSchemaError(str(exc)) from exc
    return tuple(rules)


def registry_from_dict(data: dict[str, Any]) -> MechanicRegistry:
    """Build a registry while retaining provenance from its source document."""
    rules = definitions_from_dict(data)
    return MechanicRegistry(rules, data.get("registry_version", str(SCHEMA_VERSION)))


def _object_field(item: dict[str, Any], key: str) -> dict[str, Any]:
    value = item.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def load_mechanic_definitions(path: str | Path) -> tuple[MechanicRule, ...]:
    """Compatibility helper; prefer :func:`load_mechanic_registry`."""
    return definitions_from_dict(_read_document(path))


def _read_document(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MechanicSchemaError(f"cannot read mechanic definitions {path}: {exc}") from exc
    return data


def load_mechanic_registry(path: str | Path) -> MechanicRegistry:
    """Load the canonical registry, including document registry-version provenance."""
    return registry_from_dict(_read_document(path))
