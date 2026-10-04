"""Discover completed boss encounters from WCL report metadata only."""

from dataclasses import dataclass
import math
from numbers import Real

from app.pull_coach.workflow import (encounter_identity, is_boss_fight,
                                     normalize_encounter_id, source_report_url)
from app.pull_coach.identity import fight_sort_key
from app.web_requests.warcraft_logs import WCLClient, parse_report_code
from app.web_requests.warcraft_logs.errors import MalformedResponse


class NoCatalogEncounters(Exception):
    """The report contains no completed eligible boss pulls."""


@dataclass(frozen=True)
class HistoricalEncounterSummary:
    encounter_id: str
    name: str
    fight_ids: tuple[str, ...]
    pull_count: int
    has_kill: bool
    latest_fight_id: str
    best_boss_percent: float | None
    first_start_timestamp: int
    latest_start_timestamp: int
    mechanics_supported: bool


@dataclass(frozen=True)
class HistoricalEncounterCatalog:
    report_code: str
    source_url: str
    encounters: tuple[HistoricalEncounterSummary, ...]


def _valid_percent(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


class EncounterCatalogDiscovery:
    """Build a provider-independent encounter catalog without fetching event pages."""

    def __init__(self, wcl_client: WCLClient, mechanic_registry=None):
        self.wcl_client = wcl_client
        self.mechanic_registry = mechanic_registry

    def discover(self, report_reference: str) -> HistoricalEncounterCatalog:
        report_code = parse_report_code(report_reference)
        report = self.wcl_client.report_data(report_code)
        if not isinstance(report, dict) or not isinstance(report.get("fights"), list):
            raise MalformedResponse("malformed fight metadata in report")
        groups = {}
        for fight in report["fights"]:
            if not isinstance(fight, dict):
                raise MalformedResponse("malformed fight metadata in report")
            if not is_boss_fight(fight) or fight.get("inProgress") is True or fight.get("endTime") is None:
                continue
            if ("id" not in fight or "startTime" not in fight
                    or isinstance(fight["startTime"], bool)
                    or not isinstance(fight["startTime"], Real)):
                raise MalformedResponse("malformed fight metadata in report")
            encounter_id = normalize_encounter_id(fight.get("encounterID"))
            groups.setdefault(encounter_id, []).append(fight)
        if not groups:
            raise NoCatalogEncounters("report has no completed boss encounter fights")

        ordered = sorted(groups.items(), key=lambda item: fight_sort_key(min(item[1], key=fight_sort_key)))
        summaries = []
        for encounter_id, group in ordered:
            chronology = sorted(group, key=fight_sort_key)
            latest = chronology[-1]
            encounter = encounter_identity(chronology[0])
            definitions = self.mechanic_registry.for_encounter(encounter) if self.mechanic_registry else ()
            percentages = [percent for percent in (_valid_percent(f.get("bossPercentage")) for f in chronology)
                           if percent is not None]
            summaries.append(HistoricalEncounterSummary(
                encounter_id=encounter_id,
                name=encounter.name,
                fight_ids=tuple(str(f["id"]) for f in chronology),
                pull_count=len(chronology),
                has_kill=any(f.get("kill") is True for f in chronology),
                latest_fight_id=str(latest["id"]),
                best_boss_percent=min(percentages) if percentages else None,
                first_start_timestamp=chronology[0]["startTime"],
                latest_start_timestamp=latest["startTime"],
                mechanics_supported=bool(definitions),
            ))
        return HistoricalEncounterCatalog(
            report_code, source_report_url(report_reference, report_code), tuple(summaries)
        )
