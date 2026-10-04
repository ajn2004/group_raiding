"""Deterministic encounter mechanic recognition; no failure attribution."""

from dataclasses import dataclass
from typing import Any, Mapping

from app.pull_coach.models import (
    EncounterIdentity, EventType, EvidenceReference, MechanicDefinition, NormalizedEvent,
)


@dataclass(frozen=True)
class MechanicRule:
    definition: MechanicDefinition
    definition_version: str
    event_types: tuple[EventType, ...]
    weight: float = 1.0
    metadata_predicates: Mapping[str, Any] | None = None
    stopped_ability_ids: tuple[int | str, ...] = ()
    stopped_ability_metadata_field: str | None = None
    relationships: Mapping[str, Any] | None = None
    exposure_event_types: tuple[EventType, ...] = ()
    exposure_ability_ids: tuple[int | str, ...] = ()
    exposure_metadata_predicates: Mapping[str, Any] | None = None
    source_artifact: str | None = None
    source_registry_version: str | None = None


@dataclass(frozen=True)
class MechanicMatch:
    definition: MechanicDefinition
    definition_version: str
    registry_version: str
    weight: float
    relationships: Mapping[str, Any]
    source_artifact: str | None = None
    source_registry_version: str | None = None


class MechanicRegistry:
    def __init__(self, rules: tuple[MechanicRule, ...], registry_version: str = "1") -> None:
        self.registry_version = registry_version
        self._rules = tuple(sorted(rules, key=lambda rule: (
            rule.definition.encounter.encounter_id,
            rule.definition.encounter.name,
            rule.definition.mechanic_id,
        )))
        identities: set[tuple[str, str]] = set()
        selectors: set[tuple[Any, ...]] = set()
        for rule in self._rules:
            identity = (rule.definition.encounter.encounter_id, rule.definition.mechanic_id)
            if identity in identities:
                raise ValueError(f"duplicate mechanic_id {rule.definition.mechanic_id!r} for encounter")
            identities.add(identity)
            selector = (
                rule.definition.encounter.encounter_id, rule.event_types,
                tuple(sorted(set(rule.definition.ability_ids))),
                tuple(sorted(set(rule.stopped_ability_ids))),
                rule.stopped_ability_metadata_field,
                tuple(sorted((rule.metadata_predicates or {}).items())),
            )
            for key, value in (rule.metadata_predicates or {}).items():
                if value is not None and not isinstance(value, (str, int, float, bool)):
                    raise ValueError(f"metadata_predicates[{key!r}] must be a JSON scalar")
            duplicate = selector in selectors
            selectors.add(selector)
            if duplicate:
                raise ValueError(f"ambiguous duplicate mechanic rule for {rule.definition.encounter.name}")

    def for_encounter(self, encounter: EncounterIdentity) -> tuple[MechanicDefinition, ...]:
        return tuple(rule.definition for rule in self._rules
                     if rule.definition.encounter.encounter_id == encounter.encounter_id)

    @property
    def definitions(self) -> tuple[MechanicDefinition, ...]:
        """All configured definitions, in stable registry order."""
        return tuple(rule.definition for rule in self._rules)

    @property
    def rules(self) -> tuple[MechanicRule, ...]:
        """All configured rules, in stable registry order."""
        return self._rules

    def rules_for_encounter(self, encounter: EncounterIdentity) -> tuple[MechanicRule, ...]:
        """Return configured rule contracts for an encounter in stable order."""
        return tuple(rule for rule in self._rules
                     if rule.definition.encounter.encounter_id == encounter.encounter_id)

    def match(self, encounter: EncounterIdentity, event: NormalizedEvent) -> tuple[MechanicMatch, ...]:
        matches = []
        for rule in self._rules:
            definition = rule.definition
            if definition.encounter.encounter_id != encounter.encounter_id or event.event_type not in rule.event_types:
                continue
            if definition.ability_ids and event.ability_id not in definition.ability_ids:
                continue
            if rule.stopped_ability_ids and (
                rule.stopped_ability_metadata_field is None
                or event.metadata.get(rule.stopped_ability_metadata_field) not in rule.stopped_ability_ids
            ):
                continue
            if any(event.metadata.get(key) != value for key, value in (rule.metadata_predicates or {}).items()):
                continue
            matches.append(MechanicMatch(
                definition, rule.definition_version, self.registry_version,
                rule.weight, rule.relationships or {}, rule.source_artifact,
                rule.source_registry_version,
            ))
        return tuple(sorted(matches, key=lambda match: (-match.weight, match.definition.mechanic_id)))

    def exposure_matches(self, encounter: EncounterIdentity, event: NormalizedEvent) -> tuple[tuple[str, EvidenceReference], ...]:
        """Return mechanics and source evidence for configured opportunity markers."""
        found = []
        for rule in self._rules:
            if (rule.definition.encounter.encounter_id != encounter.encounter_id
                    or not rule.exposure_event_types or event.event_type not in rule.exposure_event_types):
                continue
            if rule.exposure_ability_ids and event.ability_id not in rule.exposure_ability_ids:
                continue
            if any(event.metadata.get(key) != value
                   for key, value in (rule.exposure_metadata_predicates or {}).items()):
                continue
            found.append((rule.definition.mechanic_id, EvidenceReference(
                event.evidence_id, (event.evidence_id,), "mechanic exposure marker")))
        return tuple(sorted(found, key=lambda item: item[0]))
