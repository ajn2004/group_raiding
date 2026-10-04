"""Observation-only candidate discovery from completed Warcraft Logs encounters.

The fingerprint is SHA-256 of ``warcraftlogs:report:<canonical report code>``.
The code is used only as hash input and is never included in the artifact.
"""
from collections import Counter
from hashlib import sha256
import math
from typing import Protocol

from app.pull_coach.history.inspect import inspect_snapshot
from app.pull_coach.identity import canonical_ability_id, fight_sort_key, normalize_encounter_id
from app.pull_coach.models import ActorType, CandidateMechanic, DiscoveryProvenance, EncounterDiscovery, EventType
from app.web_requests.warcraft_logs.client import parse_report_code
from app.web_requests.warcraft_logs.errors import MalformedResponse
from app.web_requests.warcraft_logs.snapshot import WCLSnapshot


class NoCompletedEncounterPulls(ValueError):
    """The report contains no completed pulls for the requested encounter."""


class DiscoveryWriter(Protocol):
    """Minimal DAL-61 writer integration point."""

    def write_discovery(self, artifact: EncounterDiscovery) -> object: ...


_EVENT_TYPES = {"damage": EventType.DAMAGE, "heal": EventType.HEAL, "cast": EventType.CAST,
                "death": EventType.DEATH, "interrupt": EventType.INTERRUPT,
                "dispel": EventType.DISPEL, "resourcechange": EventType.RESOURCE,
                "combatantinfo": EventType.OTHER}


def discovery_source_fingerprint(report_reference):
    """Stable report identity used by discovery provenance and reuse checks."""
    code = parse_report_code(report_reference)
    return sha256(f"warcraftlogs:report:{code}".encode("utf-8")).hexdigest()


def _actor_type(value):
    return {"player": ActorType.PLAYER, "npc": ActorType.NPC, "pet": ActorType.PET,
            "object": ActorType.OBJECT}.get(str(value or "").casefold(), ActorType.UNKNOWN)


class EncounterDiscoveryService:
    """Discover factual ability candidates and optionally persist through DAL-61."""

    def __init__(self, client, writer=None, *, death_window_ms=8000):
        self.client, self.writer = client, writer
        self.death_window_ms = death_window_ms

    def discover(self, report_reference, encounter_id):
        code = parse_report_code(report_reference)
        requested_id = normalize_encounter_id(encounter_id)
        if requested_id is None:
            raise ValueError("encounter_id must be a positive numeric canonical encounter ID")
        report = self.client.report_data(code)
        try:
            fights = report["fights"]
            if not isinstance(fights, list):
                raise TypeError
            selected = []
            for fight in fights:
                if not isinstance(fight, dict):
                    raise TypeError
                if normalize_encounter_id(fight.get("encounterID")) != requested_id:
                    continue
                if type(fight.get("inProgress")) is not bool or type(fight.get("kill")) is not bool:
                    raise TypeError("fight completion fields must be booleans")
                if fight["inProgress"]:
                    continue
                if fight.get("endTime") is None:
                    continue
                if type(fight["endTime"]) not in (int, float):
                    raise TypeError("fight endTime must be numeric")
                if fight.get("startTime") is None or type(fight.get("startTime")) not in (int, float):
                    raise TypeError
                if type(fight["startTime"]) is bool or not math.isfinite(fight["startTime"]) or not math.isfinite(fight["endTime"]):
                    raise ValueError("fight times must be finite")
                if fight["endTime"] < fight["startTime"]:
                    continue
                selected.append(fight)
            selected.sort(key=fight_sort_key)
            if not selected:
                raise NoCompletedEncounterPulls(f"no completed pulls for encounter {requested_id}")
            name = next((f.get("name") for f in selected if isinstance(f.get("name"), str) and f["name"]), None)
            if name is None:
                raise TypeError
        except NoCompletedEncounterPulls:
            raise
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise MalformedResponse("malformed encounter metadata in WCL report") from exc

        try:
            pages = {}
            for fight in selected:
                fight_id = int(fight["id"])
                pages[fight_id] = self.client._event_pages(code, fight)
                for page in pages[fight_id]:
                    if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                        raise TypeError
                    for event in page["data"]:
                        if (not isinstance(event, dict) or type(event.get("timestamp")) not in (int, float)
                                or not math.isfinite(event["timestamp"])
                                or isinstance(event["timestamp"], float) and not event["timestamp"].is_integer()
                                or not isinstance(event.get("type"), str)):
                            raise TypeError
                        if event["type"].casefold() == "damage" and "amount" in event:
                            amount = event["amount"]
                            if (type(amount) not in (int, float) or not math.isfinite(amount)
                                    or amount < 0):
                                raise ValueError("damage amount must be finite and non-negative")
            snapshot = WCLSnapshot(report, pages)
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            raise MalformedResponse("malformed event data during encounter discovery") from exc

        try:
            master_data = report.get("masterData", {})
            if not isinstance(master_data, dict):
                raise TypeError("masterData must be an object")
            actors = master_data.get("actors", [])
            abilities_metadata = master_data.get("abilities", [])
            if (not isinstance(actors, list) or any(not isinstance(actor, dict) for actor in actors)
                    or not isinstance(abilities_metadata, list)
                    or any(not isinstance(ability, dict) for ability in abilities_metadata)):
                raise TypeError("masterData actors and abilities must be object lists")
            facts = inspect_snapshot(snapshot, fight_ids=[f["id"] for f in selected], death_window_ms=self.death_window_ms)
            actor_by_id = {str(actor.get("id")): _actor_type(actor.get("type")) for actor in actors}
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise MalformedResponse("malformed WCL metadata or event values during discovery") from exc
        abilities = {}
        for ability in facts["abilities"]:
            raw_identity = ability.get("identity")
            aid = raw_identity if isinstance(raw_identity, str) and raw_identity.startswith("name:") else canonical_ability_id(ability["ability_id"])
            entry = abilities.setdefault(aid, {"name": ability["name"], "events": set(), "sources": Counter(),
                "targets": Counter(), "fights": Counter(), "damage": None,
                "first": int(ability["first_timestamp"]) if ability["first_timestamp"] is not None else None,
                "last": int(ability["last_timestamp"]) if ability["last_timestamp"] is not None else None, "death": 0})
            if ability["first_timestamp"] is not None:
                first = int(ability["first_timestamp"])
                entry["first"] = min(entry["first"], first) if entry["first"] is not None else first
            if ability["last_timestamp"] is not None:
                last = int(ability["last_timestamp"])
                entry["last"] = max(entry["last"], last) if entry["last"] is not None else last
            for typ, count in ability["event_types"].items():
                entry["events"].add(_EVENT_TYPES.get(typ, EventType.OTHER))
                if typ == "damage" and entry["damage"] is None:
                    entry["damage"] = 0.0
            for actor in ability["source_actors"]:
                entry["sources"][_actor_type(actor["type"])] += actor["count"]
            for target in ability["targets"]:
                entry["targets"][actor_by_id.get(str(target["actor_id"]), ActorType.UNKNOWN)] += target["count"]
            for row in ability["per_fight"]:
                entry["fights"][str(row["fight_id"])] += sum(row["event_types"].values())
            if entry["damage"] is not None:
                entry["damage"] += ability["damage"]
        for death in facts["deaths"]:
            for event in death["damage_events"]:
                identity = event.get("ability_identity")
                if identity is not None:
                    key = identity if identity.startswith("name:") else canonical_ability_id(str(identity))
                    if key in abilities:
                        abilities[key]["death"] += 1

        candidates = []
        for aid, item in abilities.items():
            damage = item["damage"]
            candidates.append(CandidateMechanic(aid, item["name"], tuple(sorted(item["events"], key=lambda t: t.value)),
                tuple(sorted(item["sources"].items(), key=lambda pair: pair[0].value)),
                tuple(sorted(item["targets"].items(), key=lambda pair: pair[0].value)),
                tuple(sorted(item["fights"].items())), damage, item["first"], item["last"], item["death"]))
        fingerprint = discovery_source_fingerprint(code)
        provenance = tuple(sorted(DiscoveryProvenance("warcraftlogs", fingerprint, str(f["id"])) for f in selected))
        artifact = EncounterDiscovery(requested_id, name, provenance,
            tuple(sorted(candidates, key=lambda c: canonical_ability_id(c.ability_id))))
        if self.writer is not None:
            self.writer.write_discovery(artifact)
        return artifact
