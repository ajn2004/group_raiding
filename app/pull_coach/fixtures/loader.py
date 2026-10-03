"""Strict loader for schema-versioned Pull Coach JSON fixtures."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.pull_coach.models import (
    Actor, EncounterIdentity, EventType, EvidenceReference, Finding,
    FindingCategory, MechanicObservation, NormalizedEvent, PullIdentity,
    PullState, RaidReportIdentity, Role, Severity, SourceIdentity,
)

SCHEMA_VERSION = 1


class FixtureError(ValueError):
    """Base exception for malformed Pull Coach fixtures."""


class FixtureSchemaError(FixtureError):
    """Fixture payload does not satisfy the supported schema."""


class UnsupportedFixtureVersion(FixtureError):
    """A fixture uses a schema version without an explicit migration."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureError(f"cannot read fixture {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FixtureSchemaError(f"{path}: top-level JSON value must be an object")
    version = value.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedFixtureVersion(
            f"{path}: schema_version {version!r} is unsupported; expected {SCHEMA_VERSION}"
        )
    return value


def _required(data: dict[str, Any], key: str, path: Path) -> Any:
    if key not in data:
        raise FixtureSchemaError(f"{path}: missing required field {key!r}")
    return data[key]


@dataclass(frozen=True)
class PullFixture:
    pull: PullIdentity
    actors: tuple[Actor, ...]
    events: tuple[NormalizedEvent, ...]
    observations: tuple[MechanicObservation, ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class RaidNight:
    schema_version: int
    report: RaidReportIdentity
    pulls: tuple[PullFixture, ...]
    assertions: dict[str, Any] | None = None


def _evidence(values: list[dict[str, Any]], path: Path) -> tuple[EvidenceReference, ...]:
    try:
        return tuple(EvidenceReference(**{**item, "event_ids": tuple(item.get("event_ids", []))})
                     for item in values)
    except (TypeError, KeyError) as exc:
        raise FixtureSchemaError(f"{path}: malformed evidence reference: {exc}") from exc


def load_pull_fixture(path: str | Path) -> PullFixture:
    path = Path(path)
    data = _read(path)
    try:
        report_data = _required(data, "report", path)
        source = SourceIdentity(**report_data["source"])
        report = RaidReportIdentity(source, report_data["report_code"])
        encounter = EncounterIdentity(**_required(data, "encounter", path))
        pull_data = _required(data, "pull", path)
        pull = PullIdentity(report, encounter,
            **{**pull_data, "state": PullState(pull_data["state"])})
        actors = tuple(Actor(**{**actor,
            "role": Role(actor["role"]) if actor.get("role") else None,
            "source": SourceIdentity(**actor["source"]) if actor.get("source") else None,
        }) for actor in _required(data, "actors", path))
        events = tuple(NormalizedEvent(**{**event, "event_type": EventType(event["event_type"]),
            "flags": frozenset(event.get("flags", []))}) for event in _required(data, "events", path))
        observations = tuple(MechanicObservation(**{**item,
            "actor_ids": tuple(item.get("actor_ids", [])),
            "evidence": _evidence(item.get("evidence", []), path)})
            for item in data.get("observations", []))
        findings = tuple(Finding(**{**item,
            "category": FindingCategory(item["category"]), "severity": Severity(item["severity"]),
            "evidence": _evidence(item.get("evidence", []), path),
            "actor_ids": tuple(item.get("actor_ids", [])),
            "roles": tuple(Role(role) for role in item.get("roles", [])),
            "related_finding_ids": tuple(item.get("related_finding_ids", []))})
            for item in data.get("findings", []))
    except FixtureError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise FixtureSchemaError(f"{path}: invalid required field or value: {exc}") from exc
    return PullFixture(pull, actors, events, observations, findings)


def _load_raid_night(path: str | Path, through_pull: int | None = None) -> RaidNight:
    path = Path(path)
    data = _read(path)
    try:
        report_data = _required(data, "report", path)
        report = RaidReportIdentity(SourceIdentity(**report_data["source"]), report_data["report_code"])
        entries = _required(data, "pulls", path)
        # Select manifest entries before opening payloads: replay prefixes never
        # read later-pull fixture data and intentionally omit global assertions.
        if not isinstance(entries, list):
            raise FixtureSchemaError(f"{path}: 'pulls' must be a list")
        for entry in entries:
            if "pull_number" not in entry or "fixture" not in entry:
                raise FixtureSchemaError(f"{path}: each pull entry requires 'pull_number' and 'fixture'")
        selected = [entry for entry in entries
                    if through_pull is None or entry["pull_number"] <= through_pull]
        pulls = tuple(load_pull_fixture(path.parent / entry["fixture"]) for entry in selected)
        if [pull.pull.pull_number for pull in pulls] != [entry["pull_number"] for entry in selected]:
            raise FixtureSchemaError(f"{path}: manifest pull_number does not match fixture payload")
        if any(pull.pull.report != report for pull in pulls):
            raise FixtureSchemaError(f"{path}: pull report identity does not match manifest")
        numbers = [pull.pull.pull_number for pull in pulls]
        if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
            raise FixtureSchemaError(f"{path}: pulls must be in strictly increasing pull order")
    except FixtureError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise FixtureSchemaError(f"{path}: invalid raid-night manifest: {exc}") from exc
    assertions = data.get("assertions") if through_pull is None else None
    return RaidNight(SCHEMA_VERSION, report, pulls, assertions)


def load_raid_night(path: str | Path) -> RaidNight:
    return _load_raid_night(path)


def load_raid_night_prefix(path: str | Path, through_pull: int) -> RaidNight:
    if through_pull < 1:
        raise ValueError("through_pull must be >= 1")
    return _load_raid_night(path, through_pull)
