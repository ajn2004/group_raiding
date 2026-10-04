"""Live report workflow, independent of Discord and presentation."""
from dataclasses import dataclass
import logging
from urllib.parse import urlparse

from app.web_requests.warcraft_logs import WCLClient, parse_report_code
from app.pull_coach.analysis import PullAnalyzer
from app.pull_coach.progression import ProgressionComparator
from app.pull_coach.coaching import CoachingSynthesizer
from app.pull_coach.identity import fight_sort_key, normalize_encounter_id

log = logging.getLogger(__name__)


class PullCoachWorkflowError(Exception):
    """Expected, user-displayable workflow failure."""


class NoCompletedPulls(PullCoachWorkflowError): pass
class InvalidFightSelector(PullCoachWorkflowError): pass
class FightNotFound(PullCoachWorkflowError): pass
class FightNotCompleted(PullCoachWorkflowError): pass
class UnsupportedEncounter(PullCoachWorkflowError): pass
class PullCoachConfigurationError(PullCoachWorkflowError): pass


@dataclass(frozen=True)
class PullCoachReportResult:
    report_code: str
    source_url: str
    selected_pull: object
    target_ingestion: object
    analysis: object
    progression: object
    coaching: object
    historical_context: object | None = None


@dataclass(frozen=True)
class HistoricalSampleContext:
    completed_pull_count: int


DEFAULT_WCL_HOST = "classic.warcraftlogs.com"
SUPPORTED_WCL_HOSTS = {"warcraftlogs.com", "www.warcraftlogs.com", "classic.warcraftlogs.com",
                       "vanilla.warcraftlogs.com", "sod.warcraftlogs.com"}


def source_report_url(reference: str, report_code: str, fight_id: str | None = None) -> str:
    """Build the canonical credential-free WCL link shared by live and replay."""
    parsed = urlparse(reference) if isinstance(reference, str) else None
    host = parsed.hostname if parsed and parsed.hostname in SUPPORTED_WCL_HOSTS else DEFAULT_WCL_HOST
    suffix = f"?fight={fight_id}" if fight_id is not None else ""
    return f"https://{host}/reports/{report_code}{suffix}"


class PullCoachWorkflow:
    def __init__(self, wcl_client: WCLClient, analyzer: PullAnalyzer,
                 progression_comparator: ProgressionComparator,
                 coaching_synthesizer: CoachingSynthesizer):
        self.wcl_client = wcl_client
        self.analyzer = analyzer
        self.progression_comparator = progression_comparator
        self.coaching_synthesizer = coaching_synthesizer

    def run(self, report_reference: str, fight_selector: str = "latest") -> PullCoachReportResult:
        code = parse_report_code(report_reference)
        report = self.wcl_client.report_data(code)
        fights = report.get("fights", [])
        selector = str(fight_selector).strip().lower()
        if selector == "latest":
            eligible = [f for f in fights if _is_boss(f) and not f.get("inProgress") and f.get("endTime") is not None]
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
                raise UnsupportedEncounter(f"fight {selector} is not a boss encounter")
            if target.get("inProgress") or target.get("endTime") is None:
                raise FightNotCompleted(f"fight {selector} is still in progress")

        encounter_id = normalize_encounter_id(target.get("encounterID"))
        target_key = fight_sort_key(target)
        prefix = sorted((f for f in fights if normalize_encounter_id(f.get("encounterID")) == encounter_id
                         and _is_boss(f) and not f.get("inProgress") and f.get("endTime") is not None
                         and fight_sort_key(f) <= target_key), key=fight_sort_key)
        registry = getattr(self.analyzer, "registry", None)
        definitions = registry.for_encounter(_encounter(target)) if registry is not None else ()
        if not definitions:
            raise UnsupportedEncounter("no configured mechanic definitions")
        return self._run_completed_prefix(report_reference, code, prefix, target, definitions)

    def run_encounter_sample(self, report_reference: str, encounter_id: str) -> PullCoachReportResult:
        code = parse_report_code(report_reference)
        report = self.wcl_client.report_data(code)
        requested = normalize_encounter_id(encounter_id)
        if requested is None:
            raise NoCompletedPulls("invalid encounter ID")
        fights = report.get("fights", [])
        selected = [f for f in fights if normalize_encounter_id(f.get("encounterID")) == requested
                    and _is_boss(f) and f.get("inProgress") is not True and f.get("endTime") is not None]
        if not selected:
            raise NoCompletedPulls("selected encounter has no completed pulls")
        selected.sort(key=fight_sort_key)
        target = selected[-1]
        registry = getattr(self.analyzer, "registry", None)
        definitions = registry.for_encounter(_encounter(target)) if registry is not None else ()
        if not definitions:
            raise UnsupportedEncounter("no configured mechanic definitions")
        return self._run_completed_prefix(report_reference, code, selected, target, definitions,
                                          HistoricalSampleContext(len(selected)))

    def _run_completed_prefix(self, report_reference, code, prefix, target, definitions,
                              historical_context=None):
        analyses, target_ingestion = [], None
        for fight in prefix:
            log.info("Pull Coach stage=ingestion report=%s encounter=%s fight=%s",
                     code, normalize_encounter_id(fight.get("encounterID")), fight["id"])
            ingestion = self.wcl_client.ingest_fight(None, code, fight["id"])
            log.info("Pull Coach stage=analysis report=%s encounter=%s fight=%s",
                     code, ingestion.pull.encounter.encounter_id, fight["id"])
            analysis = self.analyzer.analyze(ingestion.pull, ingestion.actors, ingestion.events)
            analyses.append(analysis)
            if str(fight["id"]) == str(target["id"]):
                target_ingestion = ingestion
        if target_ingestion is None:
            raise FightNotFound(f"fight {target['id']} was not found in the selected prefix")
        log.info("Pull Coach stage=progression report=%s encounter=%s fight=%s",
                 code, target_ingestion.pull.encounter.encounter_id, target["id"])
        progression = self.progression_comparator.compare(analyses)
        labels = {item.mechanic_id: item.name for item in definitions}
        log.info("Pull Coach stage=coaching report=%s encounter=%s fight=%s",
                 code, target_ingestion.pull.encounter.encounter_id, target["id"])
        coaching = self.coaching_synthesizer.synthesize(analyses[-1], progression,
                                                        tuple(analyses[:-1]), labels)
        selected = target_ingestion.pull
        return PullCoachReportResult(code, source_report_url(report_reference, code, selected.fight_id),
                                     selected, target_ingestion, analyses[-1], progression, coaching,
                                     historical_context)


def is_boss_fight(fight):
    return isinstance(fight, dict) and normalize_encounter_id(fight.get("encounterID")) is not None


def encounter_identity(fight):
    from app.pull_coach.models import EncounterIdentity
    encounter_id = normalize_encounter_id(fight.get("encounterID"))
    if encounter_id is None:
        raise ValueError("fight has an invalid encounter ID")
    return EncounterIdentity(encounter_id, fight.get("name") or "Unknown encounter")


# Keep the historical private name for existing internal callers and integrations.
_is_boss = is_boss_fight
_encounter = encounter_identity
