"""Provider-independent, observation-only encounter discovery artifacts."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.pull_coach.identity import canonical_ability_id, normalize_encounter_id
from app.pull_coach.models.contracts import EventType

DISCOVERY_SCHEMA_VERSION = 1


class LifecycleStage(str, Enum):
    UNKNOWN = "unknown"
    DISCOVERED = "discovered"
    DRAFTED = "drafted"
    VERIFIED = "verified"
    SUPPORTED = "supported"


class ActorType(str, Enum):
    PLAYER = "player"
    NPC = "npc"
    PET = "pet"
    OBJECT = "object"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True)
class DiscoveryProvenance:
    provider: str
    source_fingerprint: str
    fight_id: str

    def __post_init__(self) -> None:
        _nonempty_string(self.provider, "provider")
        _nonempty_string(self.fight_id, "fight_id")
        if not isinstance(self.source_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", self.source_fingerprint):
            raise ValueError("source_fingerprint must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True)
class CandidateMechanic:
    """Observed ability/event aggregates; deliberately contains no coaching meaning."""

    ability_id: int | str
    ability_name: str | None
    event_types: tuple[EventType, ...]
    source_actor_type_counts: tuple[tuple[ActorType, int], ...] = ()
    target_actor_type_counts: tuple[tuple[ActorType, int], ...] = ()
    fight_occurrence_counts: tuple[tuple[str, int], ...] = ()
    damage_total: float | None = None
    first_timestamp: int | None = None
    last_timestamp: int | None = None
    death_window_observations: int = 0

    def __post_init__(self) -> None:
        if type(self.ability_id) not in (int, str) or (isinstance(self.ability_id, str) and not self.ability_id.strip()):
            raise ValueError("ability_id must be a non-empty integer or string")
        object.__setattr__(self, "ability_id", canonical_ability_id(self.ability_id))
        if self.ability_name is not None and not isinstance(self.ability_name, str):
            raise ValueError("ability_name must be a string or None")
        if not isinstance(self.event_types, tuple) or not self.event_types or any(type(x) is not EventType for x in self.event_types):
            raise ValueError("event_types must contain normalized EventType values")
        if tuple(sorted(set(self.event_types), key=lambda x: x.value)) != self.event_types:
            raise ValueError("event_types must be unique and sorted")
        _validate_counts(self.source_actor_type_counts, "source_actor_type_counts", ActorType)
        _validate_counts(self.target_actor_type_counts, "target_actor_type_counts", ActorType)
        _validate_counts(self.fight_occurrence_counts, "fight_occurrence_counts", str)
        if self.damage_total is not None and (type(self.damage_total) not in (int, float) or not math.isfinite(self.damage_total) or self.damage_total < 0):
            raise ValueError("damage_total must be a finite non-negative number or None")
        for name, value in (("first_timestamp", self.first_timestamp), ("last_timestamp", self.last_timestamp)):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if type(self.death_window_observations) is not int or self.death_window_observations < 0:
            raise ValueError("death_window_observations must be a non-negative integer")
        if self.first_timestamp is not None and self.last_timestamp is not None and self.first_timestamp > self.last_timestamp:
            raise ValueError("first_timestamp must not follow last_timestamp")


@dataclass(frozen=True)
class EncounterDiscovery:
    encounter_id: str
    encounter_name: str
    provenance: tuple[DiscoveryProvenance, ...]
    candidates: tuple[CandidateMechanic, ...]
    stage: LifecycleStage = LifecycleStage.DISCOVERED
    schema_version: int = DISCOVERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        canonical = normalize_encounter_id(self.encounter_id)
        if canonical is None or canonical != self.encounter_id:
            raise ValueError("encounter_id must be canonical")
        _nonempty_string(self.encounter_name, "encounter_name")
        if type(self.schema_version) is not int or self.schema_version != DISCOVERY_SCHEMA_VERSION:
            raise ValueError(f"unsupported discovery schema_version {self.schema_version!r}")
        if type(self.stage) is not LifecycleStage or self.stage is not LifecycleStage.DISCOVERED:
            raise ValueError("discovery artifacts must remain at the discovered lifecycle stage")
        if not isinstance(self.provenance, tuple) or any(type(p) is not DiscoveryProvenance for p in self.provenance):
            raise ValueError("provenance must contain DiscoveryProvenance values")
        if tuple(sorted(set(self.provenance))) != self.provenance:
            raise ValueError("provenance must be unique and sorted")
        if not isinstance(self.candidates, tuple) or any(type(c) is not CandidateMechanic for c in self.candidates):
            raise ValueError("candidates must contain CandidateMechanic values")
        if tuple(sorted(self.candidates, key=_candidate_key)) != self.candidates:
            raise ValueError("candidates must be sorted deterministically")
        identities = [_candidate_key(candidate) for candidate in self.candidates]
        if len(identities) != len(set(identities)):
            raise ValueError("candidate ability identities must be unique")


def _nonempty_string(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _validate_counts(collection: Any, name: str, key_type: type[Enum] | type[str]) -> None:
    if not isinstance(collection, tuple):
        raise ValueError(f"{name} must be a tuple")
    keys = []
    for pair in collection:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ValueError(f"{name} entries must be key/count pairs")
        key, count = pair
        if key_type is str:
            _nonempty_string(key, f"{name} key")
        elif type(key) is not key_type:
            raise ValueError(f"{name} keys must be {key_type.__name__} values")
        if type(count) is not int or count < 0:
            raise ValueError(f"{name} counts must be non-negative integers")
        keys.append(key.value if isinstance(key, Enum) else key)
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ValueError(f"{name} keys must be unique and sorted")


def _candidate_key(candidate: CandidateMechanic) -> str:
    return canonical_ability_id(candidate.ability_id)


def discovery_to_dict(discovery: EncounterDiscovery) -> dict[str, Any]:
    return {
        "schema_version": discovery.schema_version,
        "stage": discovery.stage.value,
        "encounter": {"id": discovery.encounter_id, "name": discovery.encounter_name},
        "provenance": [{"provider": p.provider, "source_fingerprint": p.source_fingerprint, "fight_id": p.fight_id} for p in discovery.provenance],
        "candidates": [{
            "ability_id": c.ability_id, "ability_name": c.ability_name,
            "event_types": [x.value for x in c.event_types],
            "source_actor_type_counts": [[x.value, n] for x, n in c.source_actor_type_counts],
            "target_actor_type_counts": [[x.value, n] for x, n in c.target_actor_type_counts],
            "fight_occurrence_counts": [list(x) for x in c.fight_occurrence_counts],
            "damage_total": c.damage_total, "first_timestamp": c.first_timestamp,
            "last_timestamp": c.last_timestamp, "death_window_observations": c.death_window_observations,
        } for c in discovery.candidates],
    }


def discovery_to_json(discovery: EncounterDiscovery) -> str:
    return json.dumps(discovery_to_dict(discovery), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def discovery_from_json(document: str) -> EncounterDiscovery:
    try:
        data = json.loads(document, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if not isinstance(data, dict) or set(data) != {"schema_version", "stage", "encounter", "provenance", "candidates"}:
            raise ValueError("discovery document has unexpected fields")
        if type(data["schema_version"]) is not int or data["schema_version"] != DISCOVERY_SCHEMA_VERSION:
            raise ValueError(f"unsupported discovery schema_version {data['schema_version']!r}")
        if data["stage"] != LifecycleStage.DISCOVERED.value:
            raise ValueError("only discovered artifacts can be loaded")
        encounter = data["encounter"]
        if not isinstance(encounter, dict) or set(encounter) != {"id", "name"}:
            raise ValueError("encounter must contain exactly id and name")
        if not isinstance(data["provenance"], list) or not isinstance(data["candidates"], list):
            raise ValueError("provenance and candidates must be arrays")
        provenance = tuple(sorted(DiscoveryProvenance(**item) for item in data["provenance"] if isinstance(item, dict)))
        if len(provenance) != len(data["provenance"]):
            raise ValueError("provenance entries must be objects")
        candidates = []
        expected = {"ability_id", "ability_name", "event_types", "source_actor_type_counts", "target_actor_type_counts", "fight_occurrence_counts", "damage_total", "first_timestamp", "last_timestamp", "death_window_observations"}
        for item in data["candidates"]:
            if not isinstance(item, dict) or set(item) != expected:
                raise ValueError("candidate contains missing or unexpected fields")
            item = dict(item)
            for key in ("source_actor_type_counts", "target_actor_type_counts", "fight_occurrence_counts"):
                if not isinstance(item[key], list):
                    raise ValueError(f"{key} must be an array")
                item[key] = tuple(tuple(value) if isinstance(value, list) else value for value in item[key])
            if not isinstance(item["event_types"], list):
                raise ValueError("event_types must be an array")
            item["event_types"] = tuple(EventType(value) for value in item["event_types"])
            item["source_actor_type_counts"] = tuple((ActorType(key), count) for key, count in item["source_actor_type_counts"])
            item["target_actor_type_counts"] = tuple((ActorType(key), count) for key, count in item["target_actor_type_counts"])
            candidates.append(CandidateMechanic(**item))
        return EncounterDiscovery(encounter["id"], encounter["name"], provenance, tuple(sorted(candidates, key=_candidate_key)))
    except (KeyError, TypeError, json.JSONDecodeError, OverflowError, ValueError) as exc:
        raise ValueError(f"invalid discovery artifact: {exc}") from exc
