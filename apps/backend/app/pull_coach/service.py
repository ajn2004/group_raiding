"""Source-agnostic facade retaining PullCoachWorkflow's public selectors."""
from __future__ import annotations

import os
from dataclasses import dataclass

from app.pull_coach.identity import fight_sort_key, normalize_encounter_id
from app.pull_coach.orchestration import CoachingOrchestrator, SourceMode, SourceSelection

from app.pull_coach.workflow import (
    FightNotCompleted, FightNotFound, InvalidFightSelector, NoCompletedPulls,
    PullCoachWorkflow, is_completed_boss_fight, _is_boss,
)
from app.web_requests.warcraft_logs import WCLClient, parse_report_code


def source_selection_from_env(environ=None) -> SourceSelection:
    env = os.environ if environ is None else environ
    mode = SourceMode(env.get("PULL_COACH_SOURCE", "wipefest").strip().lower())
    fallback_value = env.get("PULL_COACH_LEGACY_FALLBACK", "false").strip().lower()
    if fallback_value not in {"true", "false"}:
        raise ValueError("PULL_COACH_LEGACY_FALLBACK must be true or false")
    return SourceSelection(mode, fallback_value == "true")


@dataclass(frozen=True)
class CompletedFight:
    fight_id: str
    encounter_id: str | None
    encounter_name: str
    is_kill: bool
    boss_percentage: float | None
    start_time: int | None
    end_time: int


def completed_fight_from_wcl(fight) -> CompletedFight:
    return CompletedFight(
        fight_id=str(fight["id"]), encounter_id=str(fight["encounterID"]) if fight.get("encounterID") is not None else None,
        encounter_name=str(fight.get("name") or "Unknown encounter"), is_kill=bool(fight.get("kill")),
        boss_percentage=fight.get("bossPercentage"), start_time=fight.get("startTime"), end_time=fight["endTime"],
    )


class PullCoachService:
    def __init__(self, wcl_client: WCLClient, orchestrator: CoachingOrchestrator):
        self.wcl_client, self.orchestrator = wcl_client, orchestrator
        self.analyzer = getattr(getattr(orchestrator.legacy, "workflow", None), "analyzer", None)

    def list_completed_fights(self, report_reference: str) -> tuple[CompletedFight, ...]:
        code = parse_report_code(report_reference)
        fights = self.wcl_client.report_data(code).get("fights", [])
        eligible = sorted((fight for fight in fights if is_completed_boss_fight(fight)), key=fight_sort_key)
        return tuple(completed_fight_from_wcl(fight) for fight in eligible)

    def run(self, report_reference: str, fight_selector: str = "latest"):
        code = parse_report_code(report_reference)
        fights = self.wcl_client.report_data(code).get("fights", [])
        selector = str(fight_selector).strip().lower()
        if selector == "latest":
            eligible = [f for f in fights if is_completed_boss_fight(f)]
            if not eligible:
                raise NoCompletedPulls("report has no completed boss encounter fights")
            target = max(eligible, key=fight_sort_key)
        else:
            if not selector.isdigit():
                raise InvalidFightSelector("fight must be 'latest' or a Warcraft Logs fight ID")
            target = next((f for f in fights if str(f.get("id")) == selector), None)
            if target is None:
                raise FightNotFound(f"fight {selector} was not found")
            if not _is_boss(target):
                raise FightNotFound(f"fight {selector} is not a boss encounter")
            if not is_completed_boss_fight(target):
                raise FightNotCompleted(f"fight {selector} is still in progress")
        return self.orchestrator.coach(report_reference, target)

    def run_player(self, report_reference: str, fight_selector: str, character: str):
        code = parse_report_code(report_reference)
        fights = self.wcl_client.report_data(code).get("fights", [])
        selector = str(fight_selector).strip().lower()
        if selector == "latest":
            eligible = [f for f in fights if is_completed_boss_fight(f)]
            if not eligible:
                raise NoCompletedPulls("report has no completed boss encounter fights")
            target = max(eligible, key=fight_sort_key)
        elif selector.isdigit():
            target = next((f for f in fights if str(f.get("id")) == selector), None)
            if target is None or not _is_boss(target):
                from app.pull_coach.workflow import FightNotFound
                raise FightNotFound(f"fight {selector} was not found")
            if not is_completed_boss_fight(target):
                raise FightNotCompleted(f"fight {selector} is still in progress")
        else:
            raise InvalidFightSelector("fight must be 'latest' or a Warcraft Logs fight ID")
        return self.orchestrator.coach_player(report_reference, target, character)

    def run_encounter_sample(self, report_reference: str, encounter_id: str):
        code = parse_report_code(report_reference)
        requested = normalize_encounter_id(encounter_id)
        if requested is None:
            raise NoCompletedPulls("invalid encounter ID")
        fights = self.wcl_client.report_data(code).get("fights", [])
        selected = [f for f in fights if normalize_encounter_id(f.get("encounterID")) == requested
                    and _is_boss(f) and f.get("inProgress") is not True and f.get("endTime") is not None]
        if not selected:
            raise NoCompletedPulls("selected encounter has no completed pulls")
        if self.orchestrator.selection.mode is SourceMode.LEGACY_ONLY:
            sample = getattr(self.orchestrator.legacy, "coach_encounter_sample", None)
            if sample is not None:
                return sample(report_reference, encounter_id)
        return self.orchestrator.coach(report_reference, max(selected, key=fight_sort_key))
